use std::os::fd::{BorrowedFd, IntoRawFd, OwnedFd, RawFd};
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex, MutexGuard, PoisonError};

use pyo3::exceptions::{PyOverflowError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyBytes;

use crate::array::{AppendError, ArrayBuilder};
use crate::clock::monotonic_ns;
use crate::frames::Frames;
use crate::index::{Index, Layout, Query, Writer};
use crate::memory::{Mapping, ReadOnly, WORD_BYTES, Words, Writable, reopen_read_only, seal};
use crate::ring::Ring;
use crate::sync::Ordering;

pub(crate) type Shared = Arc<Mapping>;

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

#[pyclass(frozen)]
pub(crate) struct OwnerIndex {
    pub(crate) index: Index<Shared>,
    writer: Mutex<Writer<Shared>>,
    descriptor: OwnedFd,
}

impl OwnerIndex {
    pub(crate) fn writer(&self) -> MutexGuard<'_, Writer<Shared>> {
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

    fn published(&self) -> usize {
        self.writer().published()
    }

    fn set_progress(&self, database: usize, monotonic_ns: u64) -> PyResult<()> {
        self.index
            .set_progress(database, monotonic_ns)
            .then_some(())
            .ok_or_else(|| out_of_range("database"))
    }

    fn enable_capture(&self, enabled: bool) {
        self.index.enable_capture(enabled);
    }

    #[pyo3(signature = (tokens, admission_bytes = 0, enable_telemetry = false))]
    fn session_ring(
        &self,
        tokens: usize,
        admission_bytes: usize,
        enable_telemetry: bool,
    ) -> PyResult<SessionRing> {
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
        let ring = Ring::create(memory, tokens, enable_telemetry)
            .expect("ring mapping matches the validated capacity");
        Ok(SessionRing {
            ring,
            admissions,
            descriptor: Mutex::new(Some(descriptor)),
        })
    }
}

#[pyclass(frozen)]
pub(crate) struct SessionRing {
    ring: Ring<Shared>,
    admissions: Option<Mutex<Frames<Shared>>>,
    descriptor: Mutex<Option<OwnedFd>>,
}

impl SessionRing {
    pub(crate) fn drain(&self) -> Vec<u64> {
        let mut tokens = Vec::new();
        self.ring.drain(|token| tokens.push(token));
        tokens
    }
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
    #[pyo3(signature = (index_descriptor, ring_descriptor, enable_telemetry = false))]
    fn new(
        index_descriptor: RawFd,
        ring_descriptor: RawFd,
        enable_telemetry: bool,
    ) -> PyResult<Self> {
        let mapping = Mapping::from_descriptor(borrowed(index_descriptor)?, ReadOnly)?;
        let index = Index::attach(Arc::new(mapping))
            .ok_or_else(|| invalid("the descriptor holds no index"))?;
        let ring_mapping = Mapping::from_descriptor(borrowed(ring_descriptor)?, Writable)?;
        let memory = Arc::new(ring_mapping);
        let ring = Ring::attach(memory.clone(), enable_telemetry)
            .ok_or_else(|| invalid("the descriptor holds no ring"))?;
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
struct EncodedArray {
    limit: usize,
    builder: Mutex<ArrayBuilder>,
}

impl EncodedArray {
    fn builder(&self) -> MutexGuard<'_, ArrayBuilder> {
        self.builder.lock().unwrap_or_else(PoisonError::into_inner)
    }
}

#[pymethods]
impl EncodedArray {
    #[new]
    fn new(limit: usize) -> Self {
        Self {
            limit,
            builder: Mutex::new(ArrayBuilder::default()),
        }
    }

    #[getter]
    fn retained_bytes(&self) -> usize {
        self.builder().retained()
    }

    fn append(&self, envelope: &[u8]) -> PyResult<bool> {
        self.builder()
            .append(envelope, self.limit)
            .map_err(|error| match error {
                AppendError::Malformed => invalid("value is not an encoded document envelope"),
                AppendError::Overflow => {
                    PyOverflowError::new_err("encoded array exceeds the BSON size limit")
                }
            })
    }

    fn finish<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        let bytes = self.builder().finish();
        PyBytes::new(py, &bytes)
    }

    fn clear(&self) {
        self.builder().clear();
    }
}

#[pymodule]
mod _shared_index {
    #[pymodule_export]
    use super::{EncodedArray, OwnerIndex, ReaderIndex, SessionRing};
    #[pymodule_export]
    use crate::key_encoder::find_key_encoder;
    #[pymodule_export]
    use crate::keys::{Canonicalizer, OrderedKeys, UnsafeScan};
    #[pymodule_export]
    use crate::local_cache::{LocalOwner, SharedOwner};
}
