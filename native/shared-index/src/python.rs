use std::net::TcpStream;
use std::os::fd::{BorrowedFd, FromRawFd, IntoRawFd, OwnedFd, RawFd};
use std::os::unix::net::UnixListener;
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

use crate::clock::monotonic_ns;
use crate::echo::Echo;
use crate::frames::Frames;
use crate::index::{Block, Index, Layout, Query, Writer};
use crate::memory::{Mapping, ReadOnly, WORD_BYTES, Words, Writable, reopen_read_only, seal};
use crate::relay::Relay;
use crate::ring::Ring;
use crate::sync::Ordering;

type Shared = Arc<Mapping>;

fn invalid(message: &str) -> PyErr {
    PyValueError::new_err(message.to_owned())
}

fn out_of_range(name: &str) -> PyErr {
    PyValueError::new_err(format!("{name} is outside the index layout"))
}

fn borrowed(fd: RawFd) -> PyResult<BorrowedFd<'static>> {
    if fd < 0 {
        return Err(invalid("descriptors must be non-negative"));
    }
    Ok(unsafe { BorrowedFd::borrow_raw(fd) })
}

fn duplicate_tcp(fd: RawFd) -> std::io::Result<TcpStream> {
    let duplicate = unsafe { libc::fcntl(fd, libc::F_DUPFD_CLOEXEC, 0) };
    if duplicate < 0 {
        return Err(std::io::Error::last_os_error());
    }
    // fcntl returned a new owned descriptor, independent of the caller's handle.
    Ok(TcpStream::from(unsafe { OwnedFd::from_raw_fd(duplicate) }))
}

#[pyclass(frozen, eq, hash)]
#[derive(PartialEq, Eq, Hash)]
struct Payload {
    block: Block,
}

#[pymethods]
impl Payload {
    #[getter]
    fn token(&self) -> u64 {
        self.block.token()
    }
}

#[pyclass(frozen)]
struct OwnerIndex {
    index: Index<Shared>,
    writer: Mutex<Writer<Shared>>,
    descriptor: OwnedFd,
}

impl OwnerIndex {
    fn writer(&self) -> MutexGuard<'_, Writer<Shared>> {
        self.writer.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

#[pymethods]
impl OwnerIndex {
    #[new]
    fn new(
        slots: usize,
        arena_bytes: usize,
        databases: usize,
        namespaces: usize,
        incarnation: u64,
        expiry_ns: u64,
    ) -> PyResult<Self> {
        let layout = Layout::new(
            slots,
            arena_bytes.div_ceil(WORD_BYTES),
            databases,
            namespaces,
        )
        .ok_or_else(|| invalid("invalid index layout"))?;
        let (mapping, descriptor) = Mapping::memfd(c"client-query-cache-index", layout.words())?;
        let index = Index::create(Arc::new(mapping), layout, incarnation, expiry_ns)
            .expect("index mapping matches the validated layout");
        seal(&descriptor)?;
        Ok(Self {
            writer: Mutex::new(Writer::new(index.clone())),
            index,
            descriptor,
        })
    }

    fn reader_descriptor(&self) -> PyResult<RawFd> {
        reopen_read_only(&self.descriptor)
            .map(IntoRawFd::into_raw_fd)
            .map_err(PyErr::from)
    }

    fn store(&self, payload: &[u8]) -> Option<Payload> {
        self.writer().store(payload).map(|block| Payload { block })
    }

    fn release(&self, payload: &Payload) {
        self.writer().release(payload.block);
    }

    fn snapshot<'py>(&self, py: Python<'py>, payload: &Payload) -> Option<Bound<'py, PyBytes>> {
        let writer = self.writer();
        let snapshot = writer.snapshot(payload.block)?;
        PyBytes::new_with(py, snapshot.length, |buffer| {
            snapshot.copy_into(buffer);
            Ok(())
        })
        .ok()
    }

    fn publish(
        &self,
        database: usize,
        namespace: usize,
        epoch: u64,
        identity: &[u8],
        shape: &[u8],
        payload: &Payload,
    ) -> Option<u64> {
        let query = Query {
            database,
            namespace,
            epoch,
            identity,
            shape,
        };
        self.writer().publish(&query, payload.block).ok()
    }

    fn unpublish(&self, payload: &Payload) -> bool {
        self.writer().unpublish(payload.block)
    }

    fn published(&self) -> usize {
        self.writer().published()
    }

    fn set_available(&self, database: usize, available: bool) -> PyResult<()> {
        self.index
            .set_available(database, available)
            .then_some(())
            .ok_or_else(|| out_of_range("database"))
    }

    fn set_progress(&self, database: usize, monotonic_ns: u64) -> PyResult<()> {
        self.index
            .set_progress(database, monotonic_ns)
            .then_some(())
            .ok_or_else(|| out_of_range("database"))
    }

    fn set_epoch(&self, namespace: usize, epoch: u64) -> PyResult<()> {
        self.index
            .set_epoch(namespace, epoch)
            .then_some(())
            .ok_or_else(|| out_of_range("namespace"))
    }

    fn record_write(&self, namespace: usize) -> PyResult<()> {
        self.index
            .record_write(namespace)
            .then_some(())
            .ok_or_else(|| out_of_range("namespace"))
    }

    fn enable_capture(&self, enabled: bool) {
        self.index.enable_capture(enabled);
    }

    fn validate_capture(
        &self,
        database: usize,
        namespace: usize,
        epoch: u64,
        incarnation: u64,
        token: (u64, u64, u64),
        max_age_ns: u64,
    ) -> bool {
        let query = Query {
            database,
            namespace,
            epoch,
            identity: &[],
            shape: &[],
        };
        self.index
            .validate_capture(incarnation, &query, token, monotonic_ns(), max_age_ns)
    }

    #[pyo3(signature = (tokens, admission_bytes = 0))]
    fn session_ring(&self, tokens: usize, admission_bytes: usize) -> PyResult<SessionRing> {
        let ring_words =
            Ring::<Shared>::words_for(tokens).ok_or_else(|| invalid("invalid ring capacity"))?;
        let words = if admission_bytes == 0 {
            ring_words
        } else {
            ring_words
                .checked_add(
                    Frames::<Shared>::words_for(admission_bytes)
                        .ok_or_else(|| invalid("invalid admission capacity"))?,
                )
                .ok_or_else(|| invalid("invalid admission capacity"))?
        };
        let (mapping, descriptor) = Mapping::memfd(c"client-query-cache-ring", words)?;
        let memory = Arc::new(mapping);
        let admissions = if admission_bytes == 0 {
            None
        } else {
            Some(Mutex::new(
                Frames::create(memory.clone(), ring_words, admission_bytes)
                    .expect("admission mapping matches the validated capacity"),
            ))
        };
        let ring =
            Ring::create(memory, tokens).expect("ring mapping matches the validated capacity");
        Ok(SessionRing {
            ring,
            admissions,
            descriptor: Mutex::new(Some(descriptor)),
        })
    }

    fn serve(&self, path: &str) -> PyResult<EchoOwner> {
        let listener = UnixListener::bind(path)?;
        let echo = Echo::start(self.index.clone(), listener)?;
        Ok(EchoOwner {
            echo: Mutex::new(echo),
        })
    }
}

#[pyclass(frozen)]
struct SessionRing {
    ring: Ring<Shared>,
    admissions: Option<Mutex<Frames<Shared>>>,
    descriptor: Mutex<Option<OwnedFd>>,
}

#[pymethods]
impl SessionRing {
    fn descriptor(&self) -> PyResult<RawFd> {
        self.descriptor
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .as_ref()
            .map(std::os::fd::AsRawFd::as_raw_fd)
            .ok_or_else(|| invalid("the ring descriptor is closed"))
    }

    fn close_descriptor(&self) {
        self.descriptor
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .take();
    }

    fn drain(&self) -> Vec<u64> {
        let mut tokens = Vec::new();
        self.ring.drain(|token| tokens.push(token));
        tokens
    }

    fn dropped(&self) -> u64 {
        self.ring.dropped()
    }

    #[pyo3(signature = (max_frames = None))]
    fn drain_admissions<'py>(
        &self,
        py: Python<'py>,
        max_frames: Option<usize>,
    ) -> PyResult<Vec<Bound<'py, PyBytes>>> {
        let Some(queue) = &self.admissions else {
            return Ok(Vec::new());
        };
        let frames = queue
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .drain(max_frames.unwrap_or(usize::MAX))
            .map_err(|()| invalid("damaged admission queue"))?;
        Ok(frames.iter().map(|frame| PyBytes::new(py, frame)).collect())
    }
}

#[pyclass(frozen)]
struct ReaderIndex {
    index: Index<Shared>,
    ring: Ring<Shared>,
    admissions: Option<Mutex<Frames<Shared>>>,
    incarnation: u64,
    detached: AtomicBool,
}

#[pymethods]
impl ReaderIndex {
    #[new]
    fn new(index_descriptor: RawFd, ring_descriptor: RawFd) -> PyResult<Self> {
        let mapping = Mapping::from_descriptor(borrowed(index_descriptor)?, ReadOnly)?;
        let index = Index::attach(Arc::new(mapping))
            .ok_or_else(|| invalid("the descriptor holds no index"))?;
        let ring_mapping = Mapping::from_descriptor(borrowed(ring_descriptor)?, Writable)?;
        let memory = Arc::new(ring_mapping);
        let ring =
            Ring::attach(memory.clone()).ok_or_else(|| invalid("the descriptor holds no ring"))?;
        let ring_words = ring.words();
        let admissions = if memory.words().len() == ring_words {
            None
        } else {
            Some(Mutex::new(Frames::attach(memory, ring_words).ok_or_else(
                || invalid("the descriptor holds no admission queue"),
            )?))
        };
        Ok(Self {
            incarnation: index.incarnation(),
            index,
            ring,
            admissions,
            detached: AtomicBool::new(false),
        })
    }

    #[getter]
    fn incarnation(&self) -> u64 {
        self.incarnation
    }

    #[getter]
    fn detached(&self) -> bool {
        self.detached.load(Ordering::Acquire)
    }

    #[getter]
    fn admissions_enabled(&self) -> bool {
        self.admissions.is_some()
    }

    fn lookup<'py>(
        &self,
        py: Python<'py>,
        database: usize,
        namespace: usize,
        epoch: u64,
        identity: &[u8],
        shape: &[u8],
    ) -> Option<Bound<'py, PyBytes>> {
        if self.detached.load(Ordering::Acquire) {
            return None;
        }
        let query = Query {
            database,
            namespace,
            epoch,
            identity,
            shape,
        };
        let (payload, token) = self
            .index
            .read(self.incarnation, &query, monotonic_ns(), |located| {
                let mut copied = false;
                let payload = PyBytes::new_with(py, located.payload_len, |buffer| {
                    copied = self.index.copy_payload(located, buffer);
                    Ok(())
                })
                .ok()?;
                copied.then_some(payload)
            })
            .ok()?;
        self.ring.push(token);
        Some(payload)
    }

    fn capture(&self, database: usize, namespace: usize, epoch: u64) -> Option<(u64, u64, u64)> {
        if self.detached.load(Ordering::Acquire) {
            return None;
        }
        let query = Query {
            database,
            namespace,
            epoch,
            identity: &[],
            shape: &[],
        };
        self.index.capture(self.incarnation, &query, monotonic_ns())
    }

    fn detach(&self) {
        self.detached.store(true, Ordering::Release);
    }

    fn dropped(&self) -> u64 {
        self.ring.dropped()
    }

    fn enqueue_admission(&self, frame: &[u8]) -> bool {
        if self.detached.load(Ordering::Acquire) {
            return false;
        }
        self.admissions.as_ref().is_some_and(|queue| {
            queue
                .lock()
                .unwrap_or_else(PoisonError::into_inner)
                .push(frame)
        })
    }
}

#[pyclass(frozen)]
struct EchoOwner {
    echo: Mutex<Echo>,
}

#[pymethods]
impl EchoOwner {
    fn close(&self) {
        self.echo
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .stop();
    }
}

#[pyclass(frozen)]
struct ByteRelay {
    relay: Relay,
}

#[pymethods]
impl ByteRelay {
    #[new]
    fn new() -> Self {
        Self {
            relay: Relay::new(),
        }
    }

    fn pause(&self) {
        self.relay.pause();
    }

    fn resume(&self) {
        self.relay.resume();
    }

    fn stop(&self) {
        self.relay.stop();
    }

    #[getter]
    fn bytes_sent(&self) -> u64 {
        self.relay.sent()
    }

    #[getter]
    fn bytes_received(&self) -> u64 {
        self.relay.received()
    }

    fn run(&self, py: Python<'_>, client: RawFd, upstream: RawFd) -> PyResult<()> {
        // Duplicate while the caller still holds the GIL. Python teardown can
        // then close its descriptors without invalidating the native handles.
        let client = duplicate_tcp(client)?;
        let upstream = duplicate_tcp(upstream)?;
        py.detach(|| self.relay.forward(client, upstream))
            .map_err(PyErr::from)
    }
}

#[pymodule]
mod _shared_index {
    #[pymodule_export]
    use super::{ByteRelay, EchoOwner, OwnerIndex, Payload, ReaderIndex, SessionRing};
    #[pymodule_export]
    use crate::key_encoder::find_key_encoder;
}
