use std::os::unix::net::UnixListener;
use std::sync::atomic::AtomicBool;
use std::sync::{Arc, Mutex, PoisonError};

use pyo3::exceptions::{PyOSError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyBytes;

use crate::clock::monotonic_ns;
use crate::echo::Echo;
use crate::index::{Index, Layout, Query, Writer};
use crate::memory::{Mapping, WORD_BYTES};
use crate::ring::Ring;
use crate::sync::Ordering;

type Shared = Arc<Mapping>;

fn out_of_range(name: &str) -> PyErr {
    PyValueError::new_err(format!("{name} is outside the index layout"))
}

#[pyclass(frozen)]
struct FloorIndex {
    index: Index<Shared>,
    writer: Mutex<Writer<Shared>>,
    ring: Ring<Shared>,
}

#[pymethods]
impl FloorIndex {
    #[new]
    fn new(
        slots: usize,
        arena_bytes: usize,
        databases: usize,
        namespaces: usize,
        ring_tokens: usize,
        incarnation: u64,
        expiry_ns: u64,
    ) -> PyResult<Self> {
        let layout = Layout::new(
            slots,
            arena_bytes.div_ceil(WORD_BYTES),
            databases,
            namespaces,
        )
        .ok_or_else(|| PyValueError::new_err("invalid index layout"))?;
        let ring_words = Ring::<Shared>::words_for(ring_tokens)
            .ok_or_else(|| PyValueError::new_err("invalid ring capacity"))?;
        let mapping =
            Arc::new(Mapping::anonymous_shared(layout.words()).map_err(PyOSError::new_err)?);
        let index = Index::create(mapping, layout, incarnation, expiry_ns)
            .ok_or_else(|| PyValueError::new_err("invalid index layout"))?;
        let ring = Ring::create(
            Arc::new(Mapping::anonymous_shared(ring_words).map_err(PyOSError::new_err)?),
            ring_tokens,
        )
        .ok_or_else(|| PyValueError::new_err("invalid ring capacity"))?;
        Ok(Self {
            writer: Mutex::new(Writer::new(index.clone())),
            index,
            ring,
        })
    }

    fn publish(
        &self,
        namespace: usize,
        epoch: u64,
        identity: &[u8],
        shape: &[u8],
        payload: &[u8],
        token: u64,
    ) -> bool {
        let query = Query {
            database: 0,
            namespace,
            epoch,
            identity,
            shape,
        };
        self.writer
            .lock()
            .unwrap_or_else(PoisonError::into_inner)
            .publish(&query, payload, token)
            .is_ok()
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

    fn drain(&self) -> usize {
        self.ring.drain(drop)
    }

    fn dropped(&self) -> u64 {
        self.ring.dropped()
    }

    fn reader(&self) -> FloorReader {
        FloorReader {
            incarnation: self.index.incarnation(),
            index: self.index.clone(),
            ring: self.ring.clone(),
            detached: AtomicBool::new(false),
        }
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
struct FloorReader {
    index: Index<Shared>,
    ring: Ring<Shared>,
    incarnation: u64,
    detached: AtomicBool,
}

#[pymethods]
impl FloorReader {
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
    use super::{EchoOwner, FloorIndex, FloorReader};
}
