use std::collections::{BTreeMap, HashMap, HashSet};
use std::sync::Arc;

use pyo3::prelude::*;
use pyo3::types::PyBytes;

use super::{Capture, Handle, LocalOwner, ReleaseCapture, State, Stored, namespace_names};
use crate::clock::monotonic_ns;
use crate::index::{Block, Query};
use crate::python::{OwnerIndex, SessionRing};

type Names = (Arc<str>, Arc<str>);

struct Probe {
    token: u64,
    active: usize,
    expires: u64,
    sequence: u64,
}

pub(super) struct Probes {
    ttl_ns: u64,
    entries: HashMap<Names, Probe>,
    order: BTreeMap<u64, Names>,
    sequence: u64,
    next_token: u64,
}

impl Probes {
    pub(super) fn new(ttl_ns: u64) -> Self {
        Self {
            ttl_ns,
            entries: HashMap::new(),
            order: BTreeMap::new(),
            sequence: 0,
            next_token: 0,
        }
    }

    fn expire(&mut self, now: u64) {
        while let Some((&sequence, names)) = self.order.first_key_value() {
            if self.entries[names].expires > now {
                return;
            }
            let names = self.order.remove(&sequence).expect("ordered probe");
            self.entries.remove(&names);
        }
    }

    fn insert(&mut self, names: Names, mut probe: Probe) -> u64 {
        self.sequence += 1;
        probe.sequence = self.sequence;
        self.order.insert(self.sequence, names.clone());
        let token = probe.token;
        self.entries.insert(names, probe);
        token
    }

    pub(super) fn begin(&mut self, names: Names, admissible: bool, capacity: usize) -> Option<u64> {
        let now = monotonic_ns();
        self.expire(now);
        if !admissible {
            return None;
        }
        let expires = now.saturating_add(self.ttl_ns);
        let probe = if let Some(mut probe) = self.entries.remove(&names) {
            self.order.remove(&probe.sequence);
            probe.active += 1;
            probe.expires = expires;
            probe
        } else {
            if self.entries.len() >= capacity {
                return None;
            }
            let token = self.next_token;
            self.next_token += 1;
            Probe {
                token,
                active: 1,
                expires,
                sequence: 0,
            }
        };
        Some(self.insert(names, probe))
    }

    pub(super) fn finish(&mut self, names: &Names, token: u64) {
        self.expire(monotonic_ns());
        let Some(probe) = self.entries.get_mut(names) else {
            return;
        };
        if probe.token != token {
            return;
        }
        if probe.active == 1 {
            let sequence = probe.sequence;
            self.entries.remove(names);
            self.order.remove(&sequence);
        } else {
            probe.active -= 1;
        }
    }

    pub(super) fn active(&mut self, names: &Names, token: u64) -> bool {
        self.expire(monotonic_ns());
        self.entries
            .get(names)
            .is_some_and(|probe| probe.token == token)
    }

    pub(super) fn invalidate(&mut self, names: &Names) {
        if let Some(probe) = self.entries.remove(names) {
            self.order.remove(&probe.sequence);
        }
    }

    pub(super) fn invalidate_database(&mut self, database: &str) {
        let matching: Vec<_> = self
            .entries
            .keys()
            .filter(|names| names.0.as_ref() == database)
            .cloned()
            .collect();
        for names in matching {
            self.invalidate(&names);
        }
    }

    pub(super) fn clear(&mut self) {
        self.entries.clear();
        self.order.clear();
    }

    fn snapshot(&self) -> Vec<(String, String, u64, usize)> {
        self.order
            .values()
            .map(|names| {
                let probe = &self.entries[names];
                (
                    names.0.to_string(),
                    names.1.to_string(),
                    probe.token,
                    probe.active,
                )
            })
            .collect()
    }
}

struct Published {
    token: u64,
    namespace: u64,
    identity: Option<u64>,
}

pub(super) struct Residency {
    pub(super) index: Py<OwnerIndex>,
    databases: HashMap<Arc<str>, usize>,
    capacity: usize,
    next_slot: usize,
    free_slots: Vec<usize>,
    slots: HashMap<u64, usize>,
    published: HashMap<u64, Published>,
    tokens: HashMap<u64, Handle>,
    queries: HashMap<u64, HashSet<u64>>,
    identities: HashMap<u64, HashSet<u64>>,
    available_since: HashMap<Arc<str>, Option<f64>>,
}

fn now_seconds() -> f64 {
    monotonic_ns() as f64 / 1e9
}

impl Residency {
    pub(super) fn new(index: Py<OwnerIndex>, databases: Vec<String>, capacity: usize) -> Self {
        let now = now_seconds();
        let databases: HashMap<Arc<str>, usize> = databases
            .into_iter()
            .enumerate()
            .map(|(slot, name)| (Arc::<str>::from(name), slot))
            .collect();
        for slot in databases.values() {
            index.get().index.set_available(*slot, true);
        }
        Self {
            available_since: databases
                .keys()
                .map(|name| (name.clone(), Some(now)))
                .collect(),
            index,
            databases,
            capacity,
            next_slot: 0,
            free_slots: Vec::new(),
            slots: HashMap::new(),
            published: HashMap::new(),
            tokens: HashMap::new(),
            queries: HashMap::new(),
            identities: HashMap::new(),
        }
    }

    pub(super) fn database(&self, name: &str) -> Option<usize> {
        self.databases.get(name).copied()
    }

    pub(super) fn slot(&self, namespace: u64) -> Option<usize> {
        self.slots.get(&namespace).copied()
    }

    pub(super) fn assign(&mut self, namespace: u64, epoch: u64) -> Option<usize> {
        let slot = if let Some(slot) = self.slot(namespace) {
            slot
        } else {
            let slot = if let Some(slot) = self.free_slots.pop() {
                slot
            } else if self.next_slot < self.capacity {
                self.next_slot += 1;
                self.next_slot - 1
            } else {
                return None;
            };
            self.slots.insert(namespace, slot);
            slot
        };
        self.index.get().index.set_epoch(slot, epoch);
        Some(slot)
    }

    pub(super) fn epoch_changed(&self, namespace: u64, epoch: u64) {
        if let Some(slot) = self.slot(namespace) {
            self.index.get().index.set_epoch(slot, epoch);
        }
    }

    pub(super) fn released(&mut self, namespace: u64) {
        if let Some(slot) = self.slots.remove(&namespace) {
            self.free_slots.push(slot);
        }
    }

    pub(super) fn availability_changed(&mut self, database: &str, available: bool) {
        let Some(slot) = self.database(database) else {
            return;
        };
        if let Some(since) = self.available_since.get_mut(database) {
            *since = available.then(now_seconds);
        }
        self.index.get().index.set_available(slot, available);
    }

    pub(super) fn available_since(&self, database: &str) -> Option<f64> {
        self.available_since.get(database).copied().flatten()
    }

    pub(super) fn store(&self, payload: &[u8]) -> Option<Block> {
        self.index.get().writer().store(payload)
    }

    pub(super) fn snapshot(&self, py: Python<'_>, block: Block) -> Option<Py<PyBytes>> {
        let writer = self.index.get().writer();
        let snapshot = writer.snapshot(block)?;
        PyBytes::new_with(py, snapshot.length, |buffer| {
            snapshot.copy_into(buffer);
            Ok(())
        })
        .ok()
        .map(Bound::unbind)
    }

    #[allow(
        clippy::too_many_arguments,
        reason = "publication combines the row, namespace slot, epoch and portable key"
    )]
    pub(super) fn publish(
        &mut self,
        row: Handle,
        namespace: u64,
        database: &str,
        epoch: u64,
        identity: Option<u64>,
        keys: (&[u8], &[u8]),
        block: Block,
    ) {
        let (Some(database), Some(slot)) = (self.database(database), self.slot(namespace)) else {
            return;
        };
        let query = Query {
            database,
            namespace: slot,
            epoch,
            identity: keys.0,
            shape: keys.1,
        };
        let Ok(token) = self.index.get().writer().publish(&query, block) else {
            return;
        };
        self.published.insert(
            row.slot,
            Published {
                token,
                namespace,
                identity,
            },
        );
        self.tokens.insert(token, row);
        match identity {
            Some(identity) => self
                .identities
                .entry(identity)
                .or_default()
                .insert(row.slot),
            None => self.queries.entry(namespace).or_default().insert(row.slot),
        };
    }

    pub(super) fn withdraw(&mut self, row: u64, block: Option<Block>) {
        let Some(published) = self.published.remove(&row) else {
            return;
        };
        self.tokens.remove(&published.token);
        let (key, members) = match published.identity {
            Some(identity) => (identity, &mut self.identities),
            None => (published.namespace, &mut self.queries),
        };
        if let Some(rows) = members.get_mut(&key) {
            rows.remove(&row);
            if rows.is_empty() {
                members.remove(&key);
            }
        }
        if let Some(block) = block {
            self.index.get().writer().unpublish(block);
        }
    }

    pub(super) fn release(&mut self, row: Option<u64>, stored: &Stored) {
        if let Stored::Arena(block) = stored {
            if let Some(row) = row {
                self.withdraw(row, None);
            }
            self.index.get().writer().release(*block);
        }
    }

    pub(super) fn query_rows(&self, namespace: u64) -> Vec<u64> {
        self.queries
            .get(&namespace)
            .map(|rows| rows.iter().copied().collect())
            .unwrap_or_default()
    }

    pub(super) fn identity_rows(&self, identity: u64) -> Vec<u64> {
        self.identities
            .get(&identity)
            .map(|rows| rows.iter().copied().collect())
            .unwrap_or_default()
    }

    pub(super) fn record_write(&self, namespace: u64) {
        if let Some(slot) = self.slot(namespace) {
            self.index.get().index.record_write(slot);
        }
    }

    pub(super) fn touched(&self, token: u64) -> Option<Handle> {
        self.tokens.get(&token).copied()
    }

    pub(super) fn validate_capture(
        &self,
        incarnation: u64,
        database: usize,
        namespace: usize,
        epoch: u64,
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
        self.index.get().index.validate_capture(
            incarnation,
            &query,
            token,
            monotonic_ns(),
            max_age_ns,
        )
    }

    pub(super) fn published_count(&self) -> usize {
        self.index.get().writer().published()
    }

    pub(super) fn clear(&mut self) {
        self.published.clear();
        self.tokens.clear();
        self.queries.clear();
        self.identities.clear();
    }
}

pub(super) struct SharedState {
    pub(super) probes: Probes,
    pub(super) residency: Option<Residency>,
}

#[pyclass(frozen, extends = LocalOwner, name = "SharedOwnerCore")]
pub(crate) struct SharedOwner;

fn names(namespace: &Bound<'_, PyAny>) -> PyResult<Names> {
    let (database, collection) = namespace_names(namespace)?;
    Ok((Arc::from(database.as_ref()), Arc::from(collection.as_ref())))
}

fn shared_state(state: &mut State) -> &mut SharedState {
    state.shared.as_deref_mut().expect("shared owner state")
}

fn assigned(state: &State, key: &Names) -> Option<(usize, usize)> {
    let id = state.namespace(&key.0, &key.1)?;
    let residency = state.residency()?;
    residency.database(&key.0).zip(residency.slot(id))
}

#[pymethods]
impl SharedOwner {
    #[new]
    fn new(
        py: Python<'_>,
        config: &Bound<'_, PyAny>,
        index: Option<Py<OwnerIndex>>,
        databases: Vec<String>,
        namespaces: usize,
        probe_ttl_seconds: f64,
    ) -> PyResult<PyClassInitializer<Self>> {
        let shared = SharedState {
            probes: Probes::new((probe_ttl_seconds * 1e9) as u64),
            residency: index.map(|index| Residency::new(index, databases, namespaces)),
        };
        Ok(
            PyClassInitializer::from(LocalOwner::create(py, Some(config), Some(shared))?)
                .add_subclass(Self),
        )
    }

    fn begin_namespace_metadata_probe(
        slf: &Bound<'_, Self>,
        namespace: &Bound<'_, PyAny>,
    ) -> PyResult<Option<u64>> {
        let key = names(namespace)?;
        let mut state = slf
            .as_super()
            .get()
            .state
            .lock()
            .expect("local owner mutex");
        let admissible = !state.closed
            && (state.namespace(&key.0, &key.1).is_some()
                || state.namespaces.len() < state.max_namespaces);
        let capacity = state.max_namespaces;
        Ok(shared_state(&mut state)
            .probes
            .begin(key, admissible, capacity))
    }

    fn cancel_namespace_metadata_probe(
        slf: &Bound<'_, Self>,
        namespace: &Bound<'_, PyAny>,
        token: u64,
    ) -> PyResult<()> {
        let key = names(namespace)?;
        let mut state = slf
            .as_super()
            .get()
            .state
            .lock()
            .expect("local owner mutex");
        shared_state(&mut state).probes.finish(&key, token);
        Ok(())
    }

    fn registered_namespace_metadata(
        slf: &Bound<'_, Self>,
        namespace: &Bound<'_, PyAny>,
    ) -> PyResult<Option<(u64, u64)>> {
        let key = names(namespace)?;
        let state = slf
            .as_super()
            .get()
            .state
            .lock()
            .expect("local owner mutex");
        Ok(state.namespace(&key.0, &key.1).map(|id| {
            let namespace = &state.namespaces[&id];
            (namespace.epoch, namespace.index_generation)
        }))
    }

    #[allow(
        clippy::type_complexity,
        reason = "Python receives the epoch, index generation and optional index slot"
    )]
    fn namespace_metadata_after_probe(
        slf: &Bound<'_, Self>,
        namespace: &Bound<'_, PyAny>,
        token: u64,
    ) -> PyResult<Option<(u64, u64, Option<(usize, usize)>)>> {
        let py = slf.py();
        let key = names(namespace)?;
        let python_names = namespace_names(namespace)?;
        let mut state = slf
            .as_super()
            .get()
            .state
            .lock()
            .expect("local owner mutex");
        let reserved = !state.closed && shared_state(&mut state).probes.active(&key, token);
        let registered = if reserved {
            state.register(py, namespace, &python_names)
        } else {
            None
        };
        let metadata = registered.map(|id| {
            let current = &state.namespaces[&id];
            let (epoch, index_generation) = (current.epoch, current.index_generation);
            let slot = state.residency_mut().and_then(|residency| {
                let database = residency.database(&key.0)?;
                residency.assign(id, epoch).map(|slot| (database, slot))
            });
            (epoch, index_generation, slot)
        });
        shared_state(&mut state).probes.finish(&key, token);
        Ok(metadata)
    }

    fn assigned_slot(
        slf: &Bound<'_, Self>,
        namespace: &Bound<'_, PyAny>,
    ) -> PyResult<Option<(usize, usize)>> {
        let key = names(namespace)?;
        let state = slf
            .as_super()
            .get()
            .state
            .lock()
            .expect("local owner mutex");
        Ok(assigned(&state, &key))
    }

    #[pyo3(signature = (capture, read_shape, encoded, identity_key, shape_key))]
    fn admit_identity_published(
        slf: &Bound<'_, Self>,
        capture: &Capture,
        read_shape: &Bound<'_, PyAny>,
        encoded: &Bound<'_, PyBytes>,
        identity_key: &[u8],
        shape_key: &[u8],
    ) -> PyResult<Py<PyAny>> {
        let py = slf.py();
        let owner = slf.as_super().get();
        owner.check_capture(capture)?;
        let _release = ReleaseCapture(capture);
        owner.outcome(
            py,
            owner.admit_identity_bytes(
                py,
                capture,
                read_shape,
                encoded,
                None,
                Some((identity_key, shape_key)),
            )?,
        )
    }

    #[pyo3(signature = (capture, discriminator, encoded, shape_key, *, find_source=None))]
    fn admit_namespace_published(
        slf: &Bound<'_, Self>,
        capture: &Capture,
        discriminator: &Bound<'_, PyAny>,
        encoded: &Bound<'_, PyBytes>,
        shape_key: &[u8],
        find_source: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let py = slf.py();
        let owner = slf.as_super().get();
        owner.outcome(
            py,
            owner.admit_namespace_bytes(
                py,
                capture,
                discriminator,
                encoded,
                find_source,
                Some((b"", shape_key)),
            )?,
        )
    }

    #[allow(
        clippy::too_many_arguments,
        reason = "a queued admission carries its slot, capture token and portable keys"
    )]
    #[pyo3(signature = (namespace, slot, epoch, incarnation, token, identity, shape, encoded, identity_key, shape_key, max_age_ns))]
    fn admit_local(
        slf: &Bound<'_, Self>,
        namespace: &Bound<'_, PyAny>,
        slot: (usize, usize),
        epoch: u64,
        incarnation: u64,
        token: (u64, u64, u64),
        identity: &Bound<'_, PyAny>,
        shape: &Bound<'_, PyAny>,
        encoded: &Bound<'_, PyBytes>,
        identity_key: &[u8],
        shape_key: &[u8],
        max_age_ns: u64,
    ) -> PyResult<Option<Py<PyAny>>> {
        let py = slf.py();
        let owner = slf.as_super().get();
        let key = names(namespace)?;
        let current = assigned(&owner.state.lock().expect("local owner mutex"), &key);
        if current != Some(slot) {
            return Ok(None);
        }
        let capture = owner.begin_identity_admission(py, namespace, identity)?;
        let _release = ReleaseCapture(&capture);
        let valid = owner
            .state
            .lock()
            .expect("local owner mutex")
            .residency()
            .is_some_and(|residency| {
                residency.validate_capture(incarnation, slot.0, slot.1, epoch, token, max_age_ns)
            });
        if !valid {
            return Ok(None);
        }
        Ok(Some(owner.outcome(
            py,
            owner.admit_identity_bytes(
                py,
                &capture,
                shape,
                encoded,
                None,
                Some((identity_key, shape_key)),
            )?,
        )?))
    }

    fn touch(slf: &Bound<'_, Self>, ring: &SessionRing) {
        let tokens = ring.drain();
        let mut state = slf
            .as_super()
            .get()
            .state
            .lock()
            .expect("local owner mutex");
        for token in tokens {
            if let Some(handle) = state
                .residency()
                .and_then(|residency| residency.touched(token))
                && state.resident(handle)
            {
                state.touch(handle.slot);
            }
        }
    }

    fn _probes(slf: &Bound<'_, Self>) -> Vec<(String, String, u64, usize)> {
        let mut state = slf
            .as_super()
            .get()
            .state
            .lock()
            .expect("local owner mutex");
        let probes = &mut shared_state(&mut state).probes;
        probes.expire(monotonic_ns());
        probes.snapshot()
    }

    fn published(slf: &Bound<'_, Self>) -> usize {
        slf.as_super()
            .get()
            .state
            .lock()
            .expect("local owner mutex")
            .residency()
            .map_or(0, Residency::published_count)
    }

    fn available_since(slf: &Bound<'_, Self>, database: &str) -> Option<f64> {
        slf.as_super()
            .get()
            .state
            .lock()
            .expect("local owner mutex")
            .residency()
            .and_then(|residency| residency.available_since(database))
    }
}
