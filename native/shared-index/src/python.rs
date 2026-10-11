use std::os::fd::{BorrowedFd, IntoRawFd, OwnedFd, RawFd};
use std::os::unix::net::UnixListener;
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

use pyo3::exceptions::{PyOSError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyBytes;

use crate::clock::monotonic_ns;
use crate::echo::Echo;
use crate::index::{Block, Index, Layout, Query, Writer};
use crate::memory::{Mapping, ReadOnly, WORD_BYTES, Writable, reopen_read_only, seal};
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
        let (mapping, descriptor) = Mapping::memfd(c"client-query-cache-index", layout.words())
            .map_err(PyOSError::new_err)?;
        let index = Index::create(Arc::new(mapping), layout, incarnation, expiry_ns)
            .ok_or_else(|| invalid("invalid index layout"))?;
        seal(&descriptor).map_err(PyOSError::new_err)?;
        Ok(Self {
            writer: Mutex::new(Writer::new(index.clone())),
            index,
            descriptor,
        })
    }

    fn reader_descriptor(&self) -> PyResult<RawFd> {
        reopen_read_only(&self.descriptor)
            .map(IntoRawFd::into_raw_fd)
            .map_err(PyOSError::new_err)
    }

    fn store(&self, payload: &[u8]) -> Option<Payload> {
        self.writer().store(payload).map(|block| Payload { block })
    }

    fn release(&self, payload: &Payload) {
        self.writer().release(payload.block);
    }

    fn snapshot<'py>(&self, py: Python<'py>, payload: &Payload) -> Option<Bound<'py, PyBytes>> {
        let length = self.index.snapshot_length(payload.block)?;
        let mut intact = false;
        let copy = PyBytes::new_with(py, length, |buffer| {
            intact = self.index.snapshot_into(payload.block, buffer);
            Ok(())
        })
        .ok()?;
        intact.then_some(copy)
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

    fn session_ring(&self, tokens: usize) -> PyResult<SessionRing> {
        let words =
            Ring::<Shared>::words_for(tokens).ok_or_else(|| invalid("invalid ring capacity"))?;
        let (mapping, descriptor) =
            Mapping::memfd(c"client-query-cache-ring", words).map_err(PyOSError::new_err)?;
        let ring = Ring::create(Arc::new(mapping), tokens)
            .ok_or_else(|| invalid("invalid ring capacity"))?;
        Ok(SessionRing {
            ring,
            descriptor: Mutex::new(Some(descriptor)),
        })
    }

    fn serve(&self, path: &str) -> PyResult<EchoOwner> {
        let listener = UnixListener::bind(path).map_err(PyOSError::new_err)?;
        let echo = Echo::start(self.index.clone(), listener).map_err(PyOSError::new_err)?;
        Ok(EchoOwner {
            echo: Mutex::new(echo),
        })
    }
}

#[pyclass(frozen)]
struct SessionRing {
    ring: Ring<Shared>,
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
}

#[pyclass(frozen)]
struct ReaderIndex {
    index: Index<Shared>,
    ring: Ring<Shared>,
    incarnation: u64,
    detached: AtomicBool,
}

#[pymethods]
impl ReaderIndex {
    #[new]
    fn new(index_descriptor: RawFd, ring_descriptor: RawFd) -> PyResult<Self> {
        let mapping = Mapping::from_descriptor(borrowed(index_descriptor)?, ReadOnly)
            .map_err(PyOSError::new_err)?;
        let index = Index::attach(Arc::new(mapping))
            .ok_or_else(|| invalid("the descriptor holds no index"))?;
        let ring_mapping = Mapping::from_descriptor(borrowed(ring_descriptor)?, Writable)
            .map_err(PyOSError::new_err)?;
        let ring = Ring::attach(Arc::new(ring_mapping))
            .ok_or_else(|| invalid("the descriptor holds no ring"))?;
        Ok(Self {
            incarnation: index.incarnation(),
            index,
            ring,
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

    fn detach(&self) {
        self.detached.store(true, Ordering::Release);
    }

    fn dropped(&self) -> u64 {
        self.ring.dropped()
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

#[pymodule]
mod client_query_cache_shared_index {
    #[pymodule_export]
    use super::{EchoOwner, OwnerIndex, Payload, ReaderIndex, SessionRing};
}
