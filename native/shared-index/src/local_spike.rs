//! Bounded D3 experiment. This module is absent from ordinary wheels.

use std::collections::HashMap;
use std::sync::{Arc, Mutex};

use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyTuple};

enum CompactKey {
    Tuple(Vec<CompactKey>),
    Leaf(Py<PyAny>),
}

impl CompactKey {
    fn capture(key: &Bound<'_, PyAny>) -> PyResult<Self> {
        if key.is_exact_instance_of::<PyTuple>() {
            let tuple = key.cast::<PyTuple>()?;
            let children = tuple
                .iter()
                .map(|child| Self::capture(&child))
                .collect::<PyResult<Vec<_>>>()?;
            Ok(Self::Tuple(children))
        } else {
            Ok(Self::Leaf(key.clone().unbind()))
        }
    }

    fn materialize(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        match self {
            Self::Tuple(children) => {
                let objects = children
                    .iter()
                    .map(|child| child.materialize(py))
                    .collect::<PyResult<Vec<_>>>()?;
                Ok(PyTuple::new(py, objects)?.into_any().unbind())
            }
            Self::Leaf(object) => Ok(object.clone_ref(py)),
        }
    }
}

/// Compare a reconstructed compact key with an arbitrary supported probe.
#[pyfunction]
pub fn compact_key_equal(key: &Bound<'_, PyAny>, probe: &Bound<'_, PyAny>) -> PyResult<bool> {
    CompactKey::capture(key)?
        .materialize(key.py())?
        .bind(key.py())
        .eq(probe)
}

struct Entry {
    key: Py<PyAny>,
    value: Py<PyBytes>,
    token: u64,
}

#[derive(Default)]
struct State {
    revision: u64,
    buckets: HashMap<isize, Vec<Arc<Entry>>>,
    lru: Vec<u64>,
    hits: u64,
    misses: u64,
}

impl State {
    fn advance(&mut self) -> u64 {
        self.revision = self
            .revision
            .checked_add(1)
            .expect("spike revision exhausted");
        self.revision
    }

    fn touch(&mut self, token: u64) {
        self.lru.retain(|resident| *resident != token);
        self.lru.push(token);
    }
}

/// Reference-preserving keys with native entry ownership and version checks.
/// The global revision conservatively invalidates every bucket snapshot without
/// retaining tombstones for historical probes. Production indexing is outside
/// this feasibility spike.
#[pyclass(frozen)]
#[derive(Default)]
pub struct ReferenceKeySpike {
    state: Mutex<State>,
}

impl ReferenceKeySpike {
    fn candidates(&self, hash: isize) -> (u64, Vec<Arc<Entry>>) {
        let state = self.state.lock().expect("spike mutex poisoned");
        (
            state.revision,
            state.buckets.get(&hash).cloned().unwrap_or_default(),
        )
    }

    fn matching(
        py: Python<'_>,
        candidates: &[Arc<Entry>],
        key: &Bound<'_, PyAny>,
    ) -> PyResult<Option<usize>> {
        for (index, candidate) in candidates.iter().enumerate() {
            let stored = candidate.key.bind(py);
            if stored.is(key) || stored.eq(key)? {
                return Ok(Some(index));
            }
        }
        Ok(None)
    }
}

#[pymethods]
impl ReferenceKeySpike {
    #[new]
    fn new() -> Self {
        Self::default()
    }

    fn put(&self, py: Python<'_>, key: &Bound<'_, PyAny>, value: Py<PyBytes>) -> PyResult<u64> {
        let hash = key.hash()?;
        loop {
            let (revision, candidates) = self.candidates(hash);
            let matched = Self::matching(py, &candidates, key)?;
            let committed = {
                let mut state = self.state.lock().expect("spike mutex poisoned");
                if state.revision != revision {
                    None
                } else {
                    let token = state.advance();
                    // Match dict replacement: retain the original stored key.
                    let stored_key = match matched {
                        Some(index) => candidates[index].key.clone_ref(py),
                        None => key.clone().unbind(),
                    };
                    let entry = Arc::new(Entry {
                        key: stored_key,
                        value: value.clone_ref(py),
                        token,
                    });
                    let bucket = state.buckets.entry(hash).or_default();
                    let displaced = match matched {
                        Some(index) => Some(std::mem::replace(&mut bucket[index], entry)),
                        None => {
                            bucket.push(entry);
                            None
                        }
                    };
                    if let Some(previous) = &displaced {
                        state.lru.retain(|resident| *resident != previous.token);
                    }
                    state.touch(token);
                    Some((token, displaced))
                }
            };
            // Python-owned keys/values may finalize and reenter. Drop outside
            // the lock, including snapshots superseded by reentrant mutations.
            if let Some((token, displaced)) = committed {
                drop(displaced);
                return Ok(token);
            }
        }
    }

    fn lookup(
        &self,
        py: Python<'_>,
        key: &Bound<'_, PyAny>,
    ) -> PyResult<Option<(u64, Py<PyBytes>)>> {
        let hash = key.hash()?;
        loop {
            let (revision, candidates) = self.candidates(hash);
            let matched = Self::matching(py, &candidates, key)?;
            let committed = {
                let mut state = self.state.lock().expect("spike mutex poisoned");
                if state.revision != revision {
                    None
                } else {
                    let value = match matched {
                        Some(index) => {
                            let entry = &candidates[index];
                            state.hits += 1;
                            state.touch(entry.token);
                            Some((entry.token, entry.value.clone_ref(py)))
                        }
                        None => {
                            state.misses += 1;
                            None
                        }
                    };
                    Some(value)
                }
            };
            if let Some(value) = committed {
                return Ok(value);
            }
        }
    }

    fn clear(&self) {
        let displaced = {
            let mut state = self.state.lock().expect("spike mutex poisoned");
            state.advance();
            state.lru.clear();
            std::mem::take(&mut state.buckets)
        };
        drop(displaced);
    }

    fn snapshot(&self) -> (u64, u64, u64, Vec<u64>) {
        let state = self.state.lock().expect("spike mutex poisoned");
        (state.revision, state.hits, state.misses, state.lru.clone())
    }
}
