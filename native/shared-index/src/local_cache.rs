use std::collections::{BTreeSet, HashMap, hash_map::DefaultHasher};
use std::hash::{Hash, Hasher};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex, OnceLock, Weak};

use pyo3::PyTraverseError;
use pyo3::exceptions::{PyOverflowError, PyTypeError};
use pyo3::gc::PyVisit;
use pyo3::prelude::*;
use pyo3::pybacked::PyBackedStr;
use pyo3::types::{PyBool, PyBytes, PyDict, PyTuple, PyType, PyWeakrefMethods, PyWeakrefReference};

const CHUNK: usize = 64;
const ADMITTED: usize = 0;
const OVERSIZE: usize = 1;
const STALE: usize = 2;
const UNAVAILABLE: usize = 3;
const UNENCODABLE: usize = 4;

#[derive(Clone, Copy, Default)]
struct Links {
    previous: u64,
    next: u64,
}

#[derive(Clone, Copy, Default)]
struct Chain {
    first: u64,
    last: u64,
}

#[derive(Clone, Copy)]
enum Link {
    Hash = 0,
    Namespace = 1,
    Role = 2,
}

trait Linked {
    fn links(&self, link: Link) -> Links;
    fn links_mut(&mut self, link: Link) -> &mut Links;
}

enum Slot<T> {
    Vacant(u64),
    Occupied(T),
}

struct Slots<T> {
    chunks: Vec<Box<[Slot<T>; CHUNK]>>,
    free: u64,
    count: usize,
}

impl<T> Default for Slots<T> {
    fn default() -> Self {
        Self {
            chunks: Vec::new(),
            free: 0,
            count: 0,
        }
    }
}

impl<T> Slots<T> {
    fn slot(&self, id: u64) -> &Slot<T> {
        let index = (id - 1) as usize;
        &self.chunks[index / CHUNK][index % CHUNK]
    }
    fn slot_mut(&mut self, id: u64) -> &mut Slot<T> {
        let index = (id - 1) as usize;
        &mut self.chunks[index / CHUNK][index % CHUNK]
    }
    fn get(&self, id: u64) -> Option<&T> {
        if id == 0 || id as usize > self.chunks.len() * CHUNK {
            return None;
        }
        match self.slot(id) {
            Slot::Occupied(value) => Some(value),
            Slot::Vacant(_) => None,
        }
    }
    fn get_mut(&mut self, id: u64) -> Option<&mut T> {
        if id == 0 || id as usize > self.chunks.len() * CHUNK {
            return None;
        }
        match self.slot_mut(id) {
            Slot::Occupied(value) => Some(value),
            Slot::Vacant(_) => None,
        }
    }
    fn reserve(&mut self) -> u64 {
        if self.free == 0 {
            let first = (self.chunks.len() * CHUNK) as u64 + 1;
            self.chunks.push(Box::new(std::array::from_fn(|offset| {
                Slot::Vacant(if offset + 1 == CHUNK {
                    0
                } else {
                    first + offset as u64 + 1
                })
            })));
            self.free = first;
        }
        let id = self.free;
        let Slot::Vacant(next) = self.slot(id) else {
            unreachable!("free slot");
        };
        self.free = *next;
        id
    }
    fn install(&mut self, id: u64, value: T) {
        *self.slot_mut(id) = Slot::Occupied(value);
        self.count += 1;
    }
    fn take(&mut self, id: u64) -> T {
        let free = self.free;
        let Slot::Occupied(value) = std::mem::replace(self.slot_mut(id), Slot::Vacant(free)) else {
            unreachable!("occupied slot");
        };
        self.free = id;
        self.count -= 1;
        value
    }
    fn iter(&self) -> impl Iterator<Item = &T> {
        self.chunks
            .iter()
            .flat_map(|chunk| chunk.iter())
            .filter_map(|slot| match slot {
                Slot::Occupied(value) => Some(value),
                Slot::Vacant(_) => None,
            })
    }
    fn release_empty(&mut self) {
        if self.count == 0 {
            self.chunks.clear();
            self.free = 0;
        }
    }
}

fn cycle_insert<T: Linked>(slots: &mut Slots<T>, head: &mut u64, id: u64, link: Link) {
    if *head == 0 {
        *slots.get_mut(id).expect("inserted node").links_mut(link) = Links {
            previous: id,
            next: id,
        };
        *head = id;
    } else {
        let last = slots.get(*head).expect("cycle head").links(link).previous;
        slots
            .get_mut(last)
            .expect("cycle tail")
            .links_mut(link)
            .next = id;
        slots
            .get_mut(*head)
            .expect("cycle head")
            .links_mut(link)
            .previous = id;
        *slots.get_mut(id).expect("inserted node").links_mut(link) = Links {
            previous: last,
            next: *head,
        };
    }
}

fn cycle_remove<T: Linked>(slots: &mut Slots<T>, head: &mut u64, id: u64, link: Link) {
    let links = slots.get(id).expect("removed node").links(link);
    if links.next == id {
        *head = 0;
    } else {
        slots
            .get_mut(links.previous)
            .expect("previous node")
            .links_mut(link)
            .next = links.next;
        slots
            .get_mut(links.next)
            .expect("next node")
            .links_mut(link)
            .previous = links.previous;
        if *head == id {
            *head = links.next;
        }
    }
}

fn chain_insert<T: Linked>(slots: &mut Slots<T>, chain: &mut Chain, id: u64, link: Link) {
    *slots.get_mut(id).expect("inserted node").links_mut(link) = Links {
        previous: chain.last,
        next: 0,
    };
    if chain.last == 0 {
        chain.first = id;
    } else {
        slots
            .get_mut(chain.last)
            .expect("chain tail")
            .links_mut(link)
            .next = id;
    }
    chain.last = id;
}

fn chain_remove<T: Linked>(slots: &mut Slots<T>, chain: &mut Chain, id: u64, link: Link) {
    let links = slots.get(id).expect("removed node").links(link);
    if links.previous == 0 {
        chain.first = links.next;
    } else {
        slots
            .get_mut(links.previous)
            .expect("previous node")
            .links_mut(link)
            .next = links.next;
    }
    if links.next == 0 {
        chain.last = links.previous;
    } else {
        slots
            .get_mut(links.next)
            .expect("next node")
            .links_mut(link)
            .previous = links.previous;
    }
}

#[derive(Clone, Copy, Eq, Hash, PartialEq)]
enum Kind {
    Namespace,
    Identity,
    Alias,
}

#[derive(Clone, Copy)]
struct Handle {
    slot: u64,
    token: u64,
}

struct Source {
    family: isize,
    limit: u64,
}

struct AliasPublication<'a, 'py> {
    namespace: u64,
    hash: u64,
    key: &'a Bound<'py, PyAny>,
    identity: &'a Bound<'py, PyAny>,
    metadata: Handle,
}

enum Body {
    Namespace {
        payload: Py<PyBytes>,
        weight: usize,
        generation: u64,
        source: Option<Box<Source>>,
    },
    Identity {
        payload: Py<PyBytes>,
        weight: usize,
        epoch: u64,
        identity: Handle,
        generation: u64,
    },
    Alias {
        identity: Py<PyAny>,
        metadata: Handle,
    },
}

struct Node {
    token: u64,
    namespace: u64,
    hash: u64,
    key: Py<PyAny>,
    body: Body,
}

impl Node {
    fn kind(&self) -> Kind {
        match self.body {
            Body::Namespace { .. } => Kind::Namespace,
            Body::Identity { .. } => Kind::Identity,
            Body::Alias { .. } => Kind::Alias,
        }
    }
    fn weight(&self) -> usize {
        match self.body {
            Body::Namespace { weight, .. } | Body::Identity { weight, .. } => weight,
            Body::Alias { .. } => 0,
        }
    }
    fn payload(&self) -> &Py<PyBytes> {
        match &self.body {
            Body::Namespace { payload, .. } | Body::Identity { payload, .. } => payload,
            Body::Alias { .. } => unreachable!("value payload"),
        }
    }
    fn source(&self) -> Option<&Source> {
        match &self.body {
            Body::Namespace { source, .. } => source.as_deref(),
            _ => None,
        }
    }
}

struct Row {
    node: Arc<Node>,
    links: [Links; 3],
}

impl Linked for Row {
    fn links(&self, link: Link) -> Links {
        self.links[link as usize]
    }
    fn links_mut(&mut self, link: Link) -> &mut Links {
        &mut self.links[link as usize]
    }
}

struct Identity {
    owner: Py<PyWeakrefReference>,
    resident_owner: Option<Py<IdentityOwner>>,
    hash: isize,
    token: u64,
    generation: u64,
    captures: usize,
    residents: usize,
    aliases: u64,
    links: Links,
}

impl Identity {
    fn owner<'py>(&self, py: Python<'py>) -> Option<Bound<'py, IdentityOwner>> {
        if let Some(owner) = &self.resident_owner {
            Some(owner.bind(py).clone())
        } else {
            self.owner
                .bind(py)
                .upgrade_as::<IdentityOwner>()
                .expect("native identity weak reference")
        }
    }
}

impl Linked for Identity {
    fn links(&self, _link: Link) -> Links {
        self.links
    }
    fn links_mut(&mut self, _link: Link) -> &mut Links {
        &mut self.links
    }
}

enum Family {
    One(u64, u64),
    Many(BTreeSet<(bool, u64, u64)>),
}

impl Family {
    fn insert(&mut self, limit: u64, slot: u64) {
        match self {
            Self::One(previous_limit, previous_slot) => {
                *self = Self::Many(BTreeSet::from([
                    (*previous_limit == 0, *previous_limit, *previous_slot),
                    (limit == 0, limit, slot),
                ]));
            }
            Self::Many(sources) => {
                sources.insert((limit == 0, limit, slot));
            }
        }
    }
    fn remove(&mut self, limit: u64, slot: u64) -> bool {
        match self {
            Self::One(old_limit, old_slot) => *old_limit == limit && *old_slot == slot,
            Self::Many(sources) => {
                sources.remove(&(limit == 0, limit, slot));
                if sources.len() == 1 {
                    let (_, limit, slot) = *sources.first().expect("remaining source");
                    *self = Self::One(limit, slot);
                }
                false
            }
        }
    }
    fn slots(&self) -> impl Iterator<Item = (u64, u64)> + '_ {
        let (one, many) = match self {
            Self::One(limit, slot) => (Some((*limit, *slot)), None),
            Self::Many(sources) => (None, Some(sources)),
        };
        one.into_iter().chain(
            many.into_iter()
                .flat_map(|sources| sources.iter().map(|(_, limit, slot)| (*limit, *slot))),
        )
    }
}

struct Namespace {
    python: Py<PyAny>,
    database: Arc<str>,
    collection: Arc<str>,
    epoch: u64,
    generation: u64,
    index_generation: u64,
    query_token: u64,
    watermark: u64,
    values: Chain,
    identities: HashMap<isize, u64>,
    families: HashMap<isize, Family>,
}

#[derive(Default)]
struct Database {
    names: HashMap<Arc<str>, u64>,
    order: BTreeSet<u64>,
}

#[derive(Default)]
struct Retired {
    nodes: Vec<Arc<Node>>,
    identities: Vec<Identity>,
    namespaces: Vec<Namespace>,
    owners: Vec<Py<IdentityOwner>>,
}

struct State {
    closed: bool,
    revision: u64,
    nonce: u64,
    generation: u64,
    budget: usize,
    max_entry: usize,
    max_namespaces: usize,
    used: usize,
    value_count: usize,
    names: HashMap<Arc<str>, Database>,
    namespaces: HashMap<u64, Namespace>,
    availability: HashMap<Arc<str>, (bool, u64)>,
    index: HashMap<u64, u64>,
    rows: Slots<Row>,
    identities: Slots<Identity>,
    lru: Chain,
    hits: u64,
    misses: u64,
    evictions: u64,
    oversized: u64,
    bypasses: Vec<u64>,
    unavailable_reason: usize,
    invalidated_reason: usize,
}

impl State {
    fn changed(&mut self) {
        self.revision = self
            .revision
            .checked_add(1)
            .expect("local revision exhausted");
    }
    fn token(&mut self) -> u64 {
        self.nonce = self.nonce.checked_add(1).expect("local token exhausted");
        self.nonce
    }
    fn next_generation(&mut self, minimum: u64) -> u64 {
        let generation = self.generation.max(minimum);
        self.generation = generation
            .checked_add(1)
            .expect("local generation exhausted");
        generation
    }
    fn available(&self, database: &str) -> (bool, u64) {
        self.availability
            .get(database)
            .copied()
            .unwrap_or((true, 0))
    }
    fn namespace(&self, database: &str, collection: &str) -> Option<u64> {
        self.names.get(database)?.names.get(collection).copied()
    }
    fn register(
        &mut self,
        py: Python<'_>,
        python: &Bound<'_, PyAny>,
        names: &(PyBackedStr, PyBackedStr),
    ) -> Option<u64> {
        if let Some(namespace) = self.namespace(&names.0, &names.1) {
            return Some(namespace);
        }
        if self.closed || self.namespaces.len() >= self.max_namespaces {
            return None;
        }
        let database = self
            .names
            .get_key_value::<str>(&names.0)
            .map(|(name, _)| name.clone())
            .or_else(|| {
                self.availability
                    .get_key_value::<str>(&names.0)
                    .map(|(name, _)| name.clone())
            })
            .unwrap_or_else(|| Arc::<str>::from(names.0.as_ref()));
        let collection = Arc::<str>::from(names.1.as_ref());
        let id = self.token();
        let query_token = self.token();
        let generation = self.next_generation(0);
        let database_names = self.names.entry(database.clone()).or_default();
        database_names.names.insert(collection.clone(), id);
        database_names.order.insert(id);
        self.namespaces.insert(
            id,
            Namespace {
                python: python.clone().unbind(),
                database,
                collection,
                epoch: generation,
                generation,
                index_generation: generation,
                query_token,
                watermark: 0,
                values: Chain::default(),
                identities: HashMap::new(),
                families: HashMap::new(),
            },
        );
        self.changed();
        let _ = py;
        Some(id)
    }
    fn identity(&self, handle: Handle) -> Option<&Identity> {
        self.identities
            .get(handle.slot)
            .filter(|identity| identity.token == handle.token)
    }
    fn identity_mut(&mut self, handle: Handle) -> Option<&mut Identity> {
        self.identities
            .get_mut(handle.slot)
            .filter(|identity| identity.token == handle.token)
    }
    fn insert_identity(
        &mut self,
        namespace: u64,
        owner: &Bound<'_, IdentityOwner>,
        weak: &Bound<'_, PyWeakrefReference>,
        hash: isize,
    ) -> Handle {
        let slot = self.identities.reserve();
        let token = self.token();
        let handle = Handle { slot, token };
        owner
            .get()
            .handle
            .set(handle)
            .ok()
            .expect("new identity owner");
        let namespace = self
            .namespaces
            .get_mut(&namespace)
            .expect("identity namespace");
        let generation = namespace.watermark;
        namespace.watermark += 1;
        self.identities.install(
            slot,
            Identity {
                owner: weak.clone().unbind(),
                resident_owner: None,
                hash,
                token,
                generation,
                captures: 0,
                residents: 0,
                aliases: 0,
                links: Links::default(),
            },
        );
        let head = namespace.identities.entry(hash).or_default();
        cycle_insert(&mut self.identities, head, slot, Link::Hash);
        self.changed();
        handle
    }
    fn node(&self, slot: u64) -> &Arc<Node> {
        &self.rows.get(slot).expect("resident node").node
    }
    fn node_is_current(&self, pin: &Pin) -> bool {
        self.rows
            .get(pin.slot)
            .is_some_and(|row| row.node.token == pin.node.token)
    }
    fn valid(&self, node: &Node) -> bool {
        let namespace = &self.namespaces[&node.namespace];
        match &node.body {
            Body::Namespace { generation, .. } => *generation == namespace.query_token,
            Body::Identity {
                epoch,
                identity,
                generation,
                ..
            } => {
                namespace.epoch == *epoch
                    && self
                        .identity(*identity)
                        .is_some_and(|identity| identity.generation == *generation)
            }
            Body::Alias { .. } => true,
        }
    }
    fn touch(&mut self, slot: u64) {
        if self.lru.last == slot {
            return;
        }
        chain_remove(&mut self.rows, &mut self.lru, slot, Link::Role);
        chain_insert(&mut self.rows, &mut self.lru, slot, Link::Role);
    }
    fn index_node(&mut self, node: Node) -> u64 {
        let slot = self.rows.reserve();
        let hash = node.hash;
        let namespace_id = node.namespace;
        let alias = matches!(node.body, Body::Alias { .. });
        let weight = node.weight();
        self.rows.install(
            slot,
            Row {
                node: Arc::new(node),
                links: [Links::default(); 3],
            },
        );
        let head = self.index.entry(hash).or_default();
        cycle_insert(&mut self.rows, head, slot, Link::Hash);
        if alias {
            let Body::Alias { metadata, .. } = self.node(slot).body else {
                unreachable!("alias node");
            };
            let identity = self
                .identities
                .get_mut(metadata.slot)
                .expect("alias metadata");
            cycle_insert(&mut self.rows, &mut identity.aliases, slot, Link::Role);
        } else {
            let namespace = self
                .namespaces
                .get_mut(&namespace_id)
                .expect("value namespace");
            chain_insert(&mut self.rows, &mut namespace.values, slot, Link::Namespace);
            if let Some(source) = self.rows.get(slot).expect("source node").node.source() {
                match namespace.families.entry(source.family) {
                    std::collections::hash_map::Entry::Vacant(entry) => {
                        entry.insert(Family::One(source.limit, slot));
                    }
                    std::collections::hash_map::Entry::Occupied(mut entry) => {
                        entry.get_mut().insert(source.limit, slot)
                    }
                }
            }
            chain_insert(&mut self.rows, &mut self.lru, slot, Link::Role);
            self.used += weight;
            self.value_count += 1;
        }
        self.changed();
        slot
    }
    fn unindex_node(&mut self, slot: u64, hash: u64) {
        let head = self.index.get_mut(&hash).expect("node index");
        cycle_remove(&mut self.rows, head, slot, Link::Hash);
        if *head == 0 {
            self.index.remove(&hash);
        }
        self.changed();
    }
    fn remove_alias(&mut self, slot: u64, retired: &mut Retired) {
        let node = self.node(slot).clone();
        let Body::Alias { metadata, .. } = node.body else {
            unreachable!("alias node");
        };
        let identity = self
            .identities
            .get_mut(metadata.slot)
            .expect("alias identity");
        cycle_remove(&mut self.rows, &mut identity.aliases, slot, Link::Role);
        self.unindex_node(slot, node.hash);
        retired.nodes.push(self.rows.take(slot).node);
    }
    fn clear_aliases(&mut self, identity: Handle, retired: &mut Retired) {
        loop {
            let head = self.identity(identity).expect("alias identity").aliases;
            if head == 0 {
                return;
            }
            self.remove_alias(head, retired);
        }
    }
    fn remove_identity(&mut self, namespace: u64, handle: Handle, retired: &mut Retired) {
        self.clear_aliases(handle, retired);
        let hash = self.identity(handle).expect("removed identity").hash;
        let heads = &mut self
            .namespaces
            .get_mut(&namespace)
            .expect("identity namespace")
            .identities;
        let head = heads.get_mut(&hash).expect("identity index");
        cycle_remove(&mut self.identities, head, handle.slot, Link::Hash);
        if *head == 0 {
            heads.remove(&hash);
        }
        retired.identities.push(self.identities.take(handle.slot));
        self.changed();
    }
    fn prune_identity(&mut self, namespace: u64, handle: Handle, retired: &mut Retired) {
        let identity = self.identity(handle).expect("identity reservation");
        if identity.captures == 0 && identity.residents == 0 {
            self.remove_identity(namespace, handle, retired);
        }
    }
    fn remove_value(&mut self, slot: u64, prune: bool, retired: &mut Retired) {
        let node = self.node(slot).clone();
        chain_remove(&mut self.rows, &mut self.lru, slot, Link::Role);
        let namespace = self
            .namespaces
            .get_mut(&node.namespace)
            .expect("value namespace");
        chain_remove(&mut self.rows, &mut namespace.values, slot, Link::Namespace);
        if let Some(source) = node.source() {
            if let Some(family) = namespace.families.get_mut(&source.family) {
                if family.remove(source.limit, slot) {
                    namespace.families.remove(&source.family);
                }
            }
        }
        self.used -= node.weight();
        self.value_count -= 1;
        self.unindex_node(slot, node.hash);
        retired.nodes.push(self.rows.take(slot).node);
        if let Body::Identity { identity, .. } = node.body {
            let metadata = self.identity_mut(identity).expect("resident identity");
            metadata.residents -= 1;
            if metadata.residents == 0 {
                retired.owners.push(
                    metadata
                        .resident_owner
                        .take()
                        .expect("resident identity owner"),
                );
            }
            if prune {
                self.prune_identity(node.namespace, identity, retired);
            }
        }
    }
    fn cleanup_empty(&mut self) {
        self.rows.release_empty();
        self.identities.release_empty();
        if self.index.is_empty() {
            self.index = HashMap::new();
        }
    }
    fn admission_gate(&mut self, database: &str, generation: u64, weight: usize) -> Option<usize> {
        let (available, current) = self.available(database);
        if !available || generation != current {
            let reason = if available {
                self.invalidated_reason
            } else {
                self.unavailable_reason
            };
            self.bypasses[reason] += 1;
            Some(UNAVAILABLE)
        } else if weight > self.max_entry {
            self.oversized += 1;
            Some(OVERSIZE)
        } else {
            None
        }
    }
}

struct Pin {
    slot: u64,
    node: Arc<Node>,
    _owner: Option<Py<IdentityOwner>>,
}

enum Pins {
    Empty,
    One(Pin),
    Many(Vec<Pin>),
}

impl Pins {
    fn push(&mut self, pin: Pin) {
        *self = match std::mem::replace(self, Self::Empty) {
            Self::Empty => Self::One(pin),
            Self::One(previous) => Self::Many(vec![previous, pin]),
            Self::Many(mut pins) => {
                pins.push(pin);
                Self::Many(pins)
            }
        };
    }
    fn iter(&self) -> std::slice::Iter<'_, Pin> {
        match self {
            Self::Empty => [].iter(),
            Self::One(pin) => std::slice::from_ref(pin).iter(),
            Self::Many(pins) => pins.iter(),
        }
    }
    fn matching(&self, py: Python<'_>, query: &Query<'_, '_>) -> PyResult<Option<&Pin>> {
        for pin in self.iter() {
            if query.matches(py, &pin.node)? {
                return Ok(Some(pin));
            }
        }
        Ok(None)
    }
}

struct MetaPin {
    handle: Handle,
    owner: Py<IdentityOwner>,
}
enum MetaPins {
    Empty,
    One(MetaPin),
    Many(Vec<MetaPin>),
}

impl MetaPins {
    fn owner(&self, py: Python<'_>, handle: Handle) -> Py<IdentityOwner> {
        self.iter()
            .find(|pin| pin.handle.token == handle.token)
            .expect("compared identity owner")
            .owner
            .clone_ref(py)
    }
    fn iter(&self) -> std::slice::Iter<'_, MetaPin> {
        match self {
            Self::Empty => [].iter(),
            Self::One(pin) => std::slice::from_ref(pin).iter(),
            Self::Many(pins) => pins.iter(),
        }
    }
    fn matching(&self, key: &Bound<'_, PyAny>) -> PyResult<Option<Handle>> {
        for pin in self.iter() {
            let stored = pin.owner.get().key.bind(key.py());
            if stored.is(key) || stored.eq(key)? {
                return Ok(Some(pin.handle));
            }
        }
        Ok(None)
    }
}

enum Query<'a, 'py> {
    Plain(&'a Bound<'py, PyAny>),
    Identity(&'a Bound<'py, PyAny>, &'a Bound<'py, PyAny>),
}

impl Query<'_, '_> {
    fn hash(&self) -> PyResult<(isize, Option<isize>)> {
        match self {
            Self::Plain(key) => Ok((key.hash()?, None)),
            Self::Identity(identity, shape) => Ok((identity.hash()?, Some(shape.hash()?))),
        }
    }
    fn matches(&self, py: Python<'_>, node: &Node) -> PyResult<bool> {
        let key = node.key.bind(py);
        match self {
            Self::Plain(probe) => Ok(key.is(*probe) || key.eq(*probe)?),
            Self::Identity(identity, shape) => {
                let key = key.cast::<PyTuple>()?;
                let stored_identity = key.get_item(0)?;
                if !stored_identity.is(*identity) && !stored_identity.eq(*identity)? {
                    return Ok(false);
                }
                let stored_shape = key.get_item(1)?;
                Ok(stored_shape.is(*shape) || stored_shape.eq(*shape)?)
            }
        }
    }
}

fn scoped_hash(namespace: u64, kind: Kind, hashes: (isize, Option<isize>)) -> u64 {
    let mut hasher = DefaultHasher::new();
    namespace.hash(&mut hasher);
    kind.hash(&mut hasher);
    hashes.hash(&mut hasher);
    hasher.finish()
}

impl State {
    fn pins(&self, py: Python<'_>, namespace: u64, kind: Kind, hash: u64) -> Pins {
        let Some(first) = self.index.get(&hash).copied() else {
            return Pins::Empty;
        };
        let mut slot = first;
        let mut pins = Pins::Empty;
        loop {
            let row = self.rows.get(slot).expect("indexed node");
            if row.node.namespace == namespace && row.node.kind() == kind {
                let owner = match row.node.body {
                    Body::Alias { metadata, .. } => self
                        .identity(metadata)
                        .and_then(|identity| identity.owner(py))
                        .map(Bound::unbind),
                    _ => None,
                };
                if kind != Kind::Alias || owner.is_some() {
                    pins.push(Pin {
                        slot,
                        node: row.node.clone(),
                        _owner: owner,
                    });
                }
            }
            slot = row.links(Link::Hash).next;
            if slot == first {
                return pins;
            }
        }
    }
    fn meta_pins(&self, py: Python<'_>, namespace: u64, hash: isize) -> MetaPins {
        let Some(first) = self
            .namespaces
            .get(&namespace)
            .and_then(|namespace| namespace.identities.get(&hash))
            .copied()
        else {
            return MetaPins::Empty;
        };
        let mut slot = first;
        let mut pins = MetaPins::Empty;
        loop {
            let identity = self.identities.get(slot).expect("indexed identity");
            if let Some(owner) = identity.owner(py) {
                let pin = MetaPin {
                    handle: Handle {
                        slot,
                        token: identity.token,
                    },
                    owner: owner.unbind(),
                };
                pins = match pins {
                    MetaPins::Empty => MetaPins::One(pin),
                    MetaPins::One(previous) => MetaPins::Many(vec![previous, pin]),
                    MetaPins::Many(mut pins) => {
                        pins.push(pin);
                        MetaPins::Many(pins)
                    }
                };
            }
            slot = identity.links.next;
            if slot == first {
                return pins;
            }
        }
    }
    fn bump(&mut self, id: u64, release: bool, retired: &mut Retired) {
        let generation = self.next_generation(self.namespaces[&id].generation + 1);
        let query_token = self.token();
        let namespace = self.namespaces.get_mut(&id).expect("reclaimed namespace");
        namespace.epoch = generation;
        namespace.generation = generation;
        namespace.index_generation = generation;
        namespace.query_token = query_token;
        namespace.families.clear();
        let heads: Vec<_> = namespace.identities.values().copied().collect();
        let mut identities = Vec::new();
        for first in heads {
            let mut slot = first;
            loop {
                let identity = self.identities.get(slot).expect("namespace identity");
                identities.push(Handle {
                    slot,
                    token: identity.token,
                });
                slot = identity.links.next;
                if slot == first {
                    break;
                }
            }
        }
        for identity in &identities {
            self.clear_aliases(*identity, retired);
        }
        while self.namespaces[&id].values.first != 0 {
            self.remove_value(self.namespaces[&id].values.first, false, retired);
        }
        for identity in identities {
            if release {
                self.remove_identity(id, identity, retired);
            } else {
                self.prune_identity(id, identity, retired);
            }
        }
        if release {
            let namespace = self.namespaces.remove(&id).expect("released namespace");
            let names = self
                .names
                .get_mut(namespace.database.as_ref())
                .expect("database names");
            names.names.remove(namespace.collection.as_ref());
            names.order.remove(&id);
            if names.names.is_empty() {
                self.names.remove(namespace.database.as_ref());
            }
            retired.namespaces.push(namespace);
        }
        self.cleanup_empty();
        self.changed();
    }
    fn close(&mut self) -> Retired {
        let mut retired = Retired::default();
        if self.closed {
            return retired;
        }
        self.closed = true;
        let namespaces: Vec<_> = self.namespaces.keys().copied().collect();
        for namespace in namespaces {
            self.bump(namespace, true, &mut retired);
        }
        // Captures can outlive the Python owner. Keep their empty authority and
        // cumulative observations, without retaining the resident arena capacity.
        self.names = HashMap::new();
        self.namespaces = HashMap::new();
        self.rows = Slots::default();
        self.identities = Slots::default();
        self.changed();
        retired
    }
}

impl State {
    fn put(
        &mut self,
        py: Python<'_>,
        node: Node,
        previous: Option<&Pin>,
        retired: &mut Retired,
    ) -> Option<Handle> {
        if let Some(previous) = previous.filter(|pin| self.node_is_current(pin)) {
            let older = match (&previous.node.body, &node.body) {
                (
                    Body::Namespace {
                        generation: old, ..
                    },
                    Body::Namespace {
                        generation: new, ..
                    },
                ) => old < new,
                (
                    Body::Identity {
                        epoch: old_epoch,
                        generation: old,
                        ..
                    },
                    Body::Identity {
                        epoch: new_epoch,
                        generation: new,
                        ..
                    },
                ) => (old_epoch, old) < (new_epoch, new),
                _ => unreachable!("matching value kinds"),
            };
            if !older {
                return None;
            }
            self.remove_value(previous.slot, true, retired);
        }
        if let Body::Identity { identity, .. } = node.body {
            let metadata = self.identity_mut(identity).expect("reserved identity");
            if metadata.residents == 0 {
                metadata.resident_owner = Some(
                    metadata
                        .owner(py)
                        .expect("reserved identity owner")
                        .unbind(),
                );
            }
            metadata.residents += 1;
        }
        let token = node.token;
        let slot = self.index_node(node);
        while self.used > self.budget {
            self.remove_value(self.lru.first, true, retired);
            self.evictions += 1;
        }
        Some(Handle { slot, token })
    }
    fn resident(&self, handle: Handle) -> bool {
        self.rows
            .get(handle.slot)
            .is_some_and(|row| row.node.token == handle.token)
    }
    fn publish_alias(
        &mut self,
        alias: AliasPublication<'_, '_>,
        previous: Option<&Pin>,
        retired: &mut Retired,
    ) {
        let AliasPublication {
            namespace,
            hash,
            key,
            identity,
            metadata,
        } = alias;
        let key = if let Some(previous) = previous {
            let key = previous.node.key.clone_ref(key.py());
            self.remove_alias(previous.slot, retired);
            key
        } else {
            key.clone().unbind()
        };
        let token = self.token();
        self.index_node(Node {
            token,
            namespace,
            hash,
            key,
            body: Body::Alias {
                identity: identity.clone().unbind(),
                metadata,
            },
        });
    }
}

const INITIALIZE: usize = 0;
const CANONICALIZE: usize = 1;
const ORDER_SENSITIVE: usize = 2;
const ENCODE: usize = 3;
const DECODE: usize = 4;
const DECODE_FIND: usize = 5;
const SNAPSHOT: usize = 6;
const ALIAS_KEY: usize = 7;
const FIND_KEY: usize = 8;
const PREPARED_FIND: usize = 9;
const CLOSED_ERROR: usize = 10;
const UNSUPPORTED_ERROR: usize = 11;
const BSON_ERROR: usize = 12;
const MISS: usize = 13;
const DEFERRED_MISS: usize = 14;
const OUTCOMES: usize = 15;
const REASONS: usize = 16;

fn namespace_names(namespace: &Bound<'_, PyAny>) -> PyResult<(PyBackedStr, PyBackedStr)> {
    Ok((
        namespace.getattr("database")?.extract()?,
        namespace.getattr("collection")?.extract()?,
    ))
}

// One GC object owns the original identity key and its alias references. The
// native index is weak while only captures refer to it; resident values retain
// it strongly. Consequently a key -> capture cycle is not rooted by the cache.
#[pyclass(
    frozen,
    weakref,
    module = "client_query_cache._shared_index",
    name = "_LocalIdentityOwner"
)]
struct IdentityOwner {
    state: Weak<Mutex<State>>,
    namespace: u64,
    handle: OnceLock<Handle>,
    key: Py<PyAny>,
}

impl IdentityOwner {
    fn reclaim(&self) {
        let (Some(state), Some(handle)) = (self.state.upgrade(), self.handle.get().copied()) else {
            return;
        };
        let mut retired = Retired::default();
        {
            let mut state = state.lock().expect("identity owner mutex");
            let Some(identity) = state.identity(handle) else {
                return;
            };
            if identity.residents != 0 {
                // A resident owner is reachable from a live Python core. GC can
                // clear it only when that core is also unreachable.
                retired = state.close();
            } else {
                state.remove_identity(self.namespace, handle, &mut retired);
                state.cleanup_empty();
            }
        }
        drop(retired);
    }
}

impl Drop for IdentityOwner {
    fn drop(&mut self) {
        self.reclaim();
    }
}

#[pymethods]
impl IdentityOwner {
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.key)?;
        let (Some(state), Some(handle)) = (self.state.upgrade(), self.handle.get().copied()) else {
            return Ok(());
        };
        let state = state.lock().expect("identity owner mutex");
        let Some(identity) = state.identity(handle) else {
            return Ok(());
        };
        let first = identity.aliases;
        if first == 0 {
            return Ok(());
        }
        let mut slot = first;
        loop {
            let row = state.rows.get(slot).expect("owned alias");
            visit.call(&row.node.key)?;
            let Body::Alias { identity, .. } = &row.node.body else {
                unreachable!("owned alias");
            };
            visit.call(identity)?;
            slot = row.links(Link::Role).next;
            if slot == first {
                return Ok(());
            }
        }
    }
    fn __clear__(&self) {
        self.reclaim();
    }
}

#[pyclass(
    frozen,
    module = "client_query_cache._shared_index",
    name = "LocalCapture"
)]
struct Capture {
    state: Arc<Mutex<State>>,
    namespace: Py<PyAny>,
    namespace_id: Option<u64>,
    identity: Option<Py<PyAny>>,
    owner: Option<Py<IdentityOwner>>,
    handle: Option<Handle>,
    generation: (u64, u64),
    query_token: u64,
    availability: u64,
    released: AtomicBool,
}

impl Capture {
    fn release_reservation(&self) {
        if self.released.swap(true, Ordering::AcqRel) {
            return;
        }
        let (Some(namespace), Some(handle)) = (self.namespace_id, self.handle) else {
            return;
        };
        let mut retired = Retired::default();
        {
            let mut state = self.state.lock().expect("local capture mutex");
            if let Some(identity) = state.identity_mut(handle) {
                identity.captures -= 1;
                state.prune_identity(namespace, handle, &mut retired);
                state.cleanup_empty();
            }
        }
    }
}

impl Drop for Capture {
    fn drop(&mut self) {
        self.release_reservation();
    }
}

#[pymethods]
impl Capture {
    #[getter]
    fn namespace(&self, py: Python<'_>) -> Py<PyAny> {
        self.namespace.clone_ref(py)
    }
    #[getter]
    fn identity(&self, py: Python<'_>) -> Py<PyAny> {
        self.identity
            .as_ref()
            .map(|identity| identity.clone_ref(py))
            .unwrap_or_else(|| py.None())
    }
    #[getter]
    fn generation_key(&self) -> (u64, u64) {
        self.generation
    }
    #[getter]
    fn generation(&self) -> u64 {
        self.generation.0
    }
    #[getter]
    fn availability_generation(&self) -> u64 {
        self.availability
    }
    #[getter]
    fn released(&self) -> bool {
        self.released.load(Ordering::Acquire)
    }
    fn release(&self) {
        self.release_reservation();
    }
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        visit.call(&self.namespace)?;
        if let Some(identity) = &self.identity {
            visit.call(identity)?;
        }
        if let Some(owner) = &self.owner {
            visit.call(owner)?;
        }
        Ok(())
    }
    fn __clear__(&self) {
        self.release_reservation();
    }
}

struct ReleaseCapture<'a>(&'a Capture);
impl Drop for ReleaseCapture<'_> {
    fn drop(&mut self) {
        self.0.release_reservation();
    }
}

enum Read {
    Hit(Py<PyBytes>),
    Miss,
    Bypass,
}

#[pyclass(
    frozen,
    module = "client_query_cache._shared_index",
    name = "LocalCacheCore"
)]
pub(crate) struct LocalOwner {
    state: Arc<Mutex<State>>,
    operations: Vec<Py<PyAny>>,
    config: Py<PyAny>,
    stream_cost: Py<PyAny>,
}

impl LocalOwner {
    fn prepare_identity_owner(
        &self,
        py: Python<'_>,
        namespace: u64,
        key: &Bound<'_, PyAny>,
    ) -> PyResult<(Py<IdentityOwner>, Py<PyWeakrefReference>)> {
        let owner = Bound::new(
            py,
            IdentityOwner {
                state: Arc::downgrade(&self.state),
                namespace,
                handle: OnceLock::new(),
                key: key.clone().unbind(),
            },
        )?;
        let weak = PyWeakrefReference::new(owner.as_any())?;
        Ok((owner.unbind(), weak.unbind()))
    }
    fn operation<'py>(&self, py: Python<'py>, index: usize) -> &Bound<'py, PyAny> {
        self.operations[index].bind(py)
    }
    fn active(&self, py: Python<'_>, state: &State) -> PyResult<()> {
        if state.closed {
            Err(PyErr::from_type(
                self.operation(py, CLOSED_ERROR).cast::<PyType>()?.clone(),
                ("cache is closed",),
            ))
        } else {
            Ok(())
        }
    }
    fn ensure_active(&self, py: Python<'_>) -> PyResult<()> {
        self.active(py, &self.state.lock().expect("local owner mutex"))
    }
    fn canonical<'py>(&self, value: &Bound<'py, PyAny>) -> PyResult<Bound<'py, PyAny>> {
        self.operation(value.py(), CANONICALIZE).call1((value,))
    }
    fn canonical_identity<'py>(
        &self,
        value: &Bound<'py, PyAny>,
        require: bool,
    ) -> PyResult<Bound<'py, PyAny>> {
        let key = self
            .operation(value.py(), ORDER_SENSITIVE)
            .call1((value,))?;
        let key = self.canonical(&key)?;
        if require && key.is_none() {
            return Err(PyErr::from_value(
                self.operation(value.py(), UNSUPPORTED_ERROR)
                    .call1(("identity must not be None",))?,
            ));
        }
        Ok(key)
    }
    fn outcome(&self, py: Python<'_>, outcome: usize) -> PyResult<Py<PyAny>> {
        Ok(self.operation(py, OUTCOMES).get_item(outcome)?.unbind())
    }
    fn encode<'py>(
        &self,
        py: Python<'py>,
        value: &Bound<'py, PyAny>,
        codec: Option<&Bound<'py, PyAny>>,
    ) -> PyResult<Option<Bound<'py, PyBytes>>> {
        match self.operation(py, ENCODE).call1((value, codec)) {
            Ok(encoded) => Ok(Some(encoded.cast_into::<PyBytes>()?)),
            Err(error)
                if error.is_instance_of::<PyOverflowError>(py)
                    || error.is_instance(py, self.operation(py, BSON_ERROR)) =>
            {
                Ok(None)
            }
            Err(error) => Err(error),
        }
    }
    fn check_capture(&self, capture: &Capture) -> PyResult<()> {
        if Arc::ptr_eq(&self.state, &capture.state) {
            Ok(())
        } else {
            Err(PyTypeError::new_err(
                "capture belongs to another cache core",
            ))
        }
    }
    fn namespace_capture_valid(state: &State, capture: &Capture) -> bool {
        !capture.released.load(Ordering::Acquire)
            && capture
                .namespace_id
                .and_then(|id| state.namespaces.get(&id))
                .is_some_and(|namespace| namespace.query_token == capture.query_token)
    }
    fn identity_capture_valid(py: Python<'_>, state: &State, capture: &Capture) -> bool {
        !capture.released.load(Ordering::Acquire)
            && capture
                .namespace_id
                .and_then(|id| state.namespaces.get(&id))
                .is_some_and(|namespace| namespace.epoch == capture.generation.0)
            && capture
                .handle
                .and_then(|handle| state.identity(handle))
                .is_some_and(|identity| {
                    identity.generation == capture.generation.1 && identity.owner(py).is_some()
                })
    }
    fn lookup_gate(&self, py: Python<'_>, database: &str) -> PyResult<bool> {
        let mut state = self.state.lock().expect("local owner mutex");
        self.active(py, &state)?;
        if state.available(database).0 {
            Ok(true)
        } else {
            let reason = state.unavailable_reason;
            state.bypasses[reason] += 1;
            Ok(false)
        }
    }
    fn lookup(
        &self,
        py: Python<'_>,
        names: &(PyBackedStr, PyBackedStr),
        kind: Kind,
        query: Query<'_, '_>,
        defer: bool,
    ) -> PyResult<Read> {
        let hashes = query.hash()?;
        loop {
            let (revision, pins) = {
                let mut state = self.state.lock().expect("local owner mutex");
                self.active(py, &state)?;
                if !state.available(&names.0).0 {
                    let reason = state.unavailable_reason;
                    state.bypasses[reason] += 1;
                    return Ok(Read::Bypass);
                }
                let Some(namespace) = state.namespace(&names.0, &names.1) else {
                    if !defer {
                        state.misses += 1;
                    }
                    return Ok(Read::Miss);
                };
                (
                    state.revision,
                    state.pins(py, namespace, kind, scoped_hash(namespace, kind, hashes)),
                )
            };
            let found = pins.matching(py, &query)?;
            let mut state = self.state.lock().expect("local owner mutex");
            self.active(py, &state)?;
            if state.revision != revision {
                continue;
            }
            if let Some(pin) =
                found.filter(|pin| state.node_is_current(pin) && state.valid(&pin.node))
            {
                state.touch(pin.slot);
                state.hits += 1;
                return Ok(Read::Hit(pin.node.payload().clone_ref(py)));
            }
            if !defer {
                state.misses += 1;
            }
            return Ok(Read::Miss);
        }
    }
    fn admit_namespace_bytes(
        &self,
        py: Python<'_>,
        capture: &Capture,
        discriminator: &Bound<'_, PyAny>,
        encoded: &Bound<'_, PyBytes>,
        find_source: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<usize> {
        self.check_capture(capture)?;
        self.ensure_active(py)?;
        let key = self.canonical(discriminator)?;
        let hashes = Query::Plain(&key).hash()?;
        let source = find_source
            .filter(|value| !value.is_none())
            .map(|source| -> PyResult<Source> {
                Ok(Source {
                    family: source.getattr("family")?.extract()?,
                    limit: source.getattr("limit")?.extract()?,
                })
            })
            .transpose()?;
        let names = namespace_names(capture.namespace.bind(py))?;
        let weight = encoded.as_bytes().len();
        loop {
            let (revision, pins, hash) = {
                let mut state = self.state.lock().expect("local owner mutex");
                self.active(py, &state)?;
                if let Some(outcome) = state.admission_gate(&names.0, capture.availability, weight)
                {
                    return Ok(outcome);
                }
                if !Self::namespace_capture_valid(&state, capture) {
                    return Ok(STALE);
                }
                let namespace = capture.namespace_id.expect("valid capture");
                let hash = scoped_hash(namespace, Kind::Namespace, hashes);
                (
                    state.revision,
                    state.pins(py, namespace, Kind::Namespace, hash),
                    hash,
                )
            };
            let previous = pins.matching(py, &Query::Plain(&key))?;
            let mut retired = Retired::default();
            let mut state = self.state.lock().expect("local owner mutex");
            self.active(py, &state)?;
            if state.revision != revision {
                continue;
            }
            if !Self::namespace_capture_valid(&state, capture) {
                return Ok(STALE);
            }
            let token = state.token();
            let node = Node {
                token,
                namespace: capture.namespace_id.expect("valid capture"),
                hash,
                key: key.clone().unbind(),
                body: Body::Namespace {
                    payload: encoded.clone().unbind(),
                    weight,
                    generation: capture.query_token,
                    source: source.as_ref().map(|source| {
                        Box::new(Source {
                            family: source.family,
                            limit: source.limit,
                        })
                    }),
                },
            };
            let handle = state.put(py, node, previous, &mut retired);
            let admitted = handle.is_some_and(|handle| state.resident(handle));
            state.cleanup_empty();
            drop(state);
            return Ok(if admitted { ADMITTED } else { STALE });
        }
    }
    fn admit_identity_bytes(
        &self,
        py: Python<'_>,
        capture: &Capture,
        read_shape: &Bound<'_, PyAny>,
        encoded: &Bound<'_, PyBytes>,
        alias: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<usize> {
        self.check_capture(capture)?;
        self.ensure_active(py)?;
        let identity = capture
            .identity
            .as_ref()
            .ok_or_else(|| PyTypeError::new_err("identity capture required"))?
            .bind(py);
        let shape = self.canonical(read_shape)?;
        let key = PyTuple::new(py, [identity, &shape])?.into_any();
        let hashes = Query::Identity(identity, &shape).hash()?;
        let alias = alias.filter(|alias| !alias.is_none());
        let alias_hash = alias.map(|alias| alias.hash()).transpose()?;
        let names = namespace_names(capture.namespace.bind(py))?;
        let weight = encoded.as_bytes().len();
        loop {
            let (revision, pins, aliases, hash, alias_hash) = {
                let mut state = self.state.lock().expect("local owner mutex");
                self.active(py, &state)?;
                if let Some(outcome) = state.admission_gate(&names.0, capture.availability, weight)
                {
                    return Ok(outcome);
                }
                if !Self::identity_capture_valid(py, &state, capture) {
                    return Ok(STALE);
                }
                let namespace = capture.namespace_id.expect("valid capture");
                let hash = scoped_hash(namespace, Kind::Identity, hashes);
                let alias_hash =
                    alias_hash.map(|hash| scoped_hash(namespace, Kind::Alias, (hash, None)));
                (
                    state.revision,
                    state.pins(py, namespace, Kind::Identity, hash),
                    alias_hash
                        .map(|hash| state.pins(py, namespace, Kind::Alias, hash))
                        .unwrap_or(Pins::Empty),
                    hash,
                    alias_hash,
                )
            };
            let previous = pins.matching(py, &Query::Identity(identity, &shape))?;
            let old_alias = alias
                .map(|alias| aliases.matching(py, &Query::Plain(alias)))
                .transpose()?
                .flatten();
            let mut retired = Retired::default();
            let mut state = self.state.lock().expect("local owner mutex");
            self.active(py, &state)?;
            if state.revision != revision {
                continue;
            }
            if !Self::identity_capture_valid(py, &state, capture) {
                return Ok(STALE);
            }
            let namespace = capture.namespace_id.expect("valid capture");
            let metadata = capture.handle.expect("identity capture");
            if let (Some(alias), Some(hash)) = (alias, alias_hash) {
                state.publish_alias(
                    AliasPublication {
                        namespace,
                        hash,
                        key: alias,
                        identity,
                        metadata,
                    },
                    old_alias,
                    &mut retired,
                );
            }
            let token = state.token();
            let node = Node {
                token,
                namespace,
                hash,
                key: key.clone().unbind(),
                body: Body::Identity {
                    payload: encoded.clone().unbind(),
                    weight,
                    epoch: capture.generation.0,
                    identity: metadata,
                    generation: capture.generation.1,
                },
            };
            let handle = state.put(py, node, previous, &mut retired);
            let admitted = handle.is_some_and(|handle| state.resident(handle));
            state.cleanup_empty();
            drop(state);
            return Ok(if admitted { ADMITTED } else { STALE });
        }
    }
}

impl Drop for LocalOwner {
    fn drop(&mut self) {
        let retired = self.state.lock().expect("local owner mutex").close();
        drop(retired);
    }
}

#[pymethods]
impl LocalOwner {
    #[new]
    #[pyo3(signature = (config=None))]
    fn new(py: Python<'_>, config: Option<&Bound<'_, PyAny>>) -> PyResult<Self> {
        let operations = py
            .import("client_query_cache._core.native")?
            .getattr("_OPERATIONS")?
            .cast_into::<PyTuple>()?;
        let setup = operations
            .get_item(INITIALIZE)?
            .call1((config,))?
            .cast_into::<PyTuple>()?;
        let reasons = operations.get_item(REASONS)?;
        let mut unavailable_reason = 0;
        let mut invalidated_reason = 0;
        let reason_count = reasons.len()?;
        for index in 0..reason_count {
            let reason = reasons.get_item(index)?.extract::<String>()?;
            if reason == "stream_unavailable" {
                unavailable_reason = index;
            }
            if reason == "admission_invalidated" {
                invalidated_reason = index;
            }
        }
        Ok(Self {
            state: Arc::new(Mutex::new(State {
                closed: false,
                revision: 0,
                nonce: 0,
                generation: 0,
                budget: setup.get_item(1)?.extract()?,
                max_entry: setup.get_item(2)?.extract()?,
                max_namespaces: setup.get_item(3)?.extract()?,
                used: 0,
                value_count: 0,
                names: HashMap::new(),
                namespaces: HashMap::new(),
                availability: HashMap::new(),
                index: HashMap::new(),
                rows: Slots::default(),
                identities: Slots::default(),
                lru: Chain::default(),
                hits: 0,
                misses: 0,
                evictions: 0,
                oversized: 0,
                bypasses: vec![0; reason_count],
                unavailable_reason,
                invalidated_reason,
            })),
            operations: operations.iter().map(Bound::unbind).collect(),
            config: setup.get_item(0)?.unbind(),
            stream_cost: setup.get_item(4)?.unbind(),
        })
    }
    fn close(&self) {
        let retired = self.state.lock().expect("local owner mutex").close();
        drop(retired);
    }
    #[getter]
    fn max_entry_bytes(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        Ok(self.config.bind(py).getattr("max_entry_bytes")?.unbind())
    }
    #[getter]
    fn max_namespaces(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        Ok(self.config.bind(py).getattr("max_namespaces")?.unbind())
    }
    fn snapshot(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        let values = {
            let state = self.state.lock().expect("local owner mutex");
            (
                state.closed,
                state.used,
                state.value_count,
                state.hits,
                state.misses,
                state.evictions,
                state.oversized,
                state.bypasses.clone(),
            )
        };
        Ok(self
            .operation(py, SNAPSHOT)
            .call1((values, self.config.bind(py)))?
            .unbind())
    }
    fn _ownership(&self) -> (usize, usize, usize, usize, usize) {
        let state = self.state.lock().expect("local owner mutex");
        (
            state.namespaces.len(),
            state.identities.count,
            state.rows.count - state.value_count,
            state
                .identities
                .iter()
                .map(|identity| identity.captures)
                .sum(),
            state
                .namespaces
                .values()
                .flat_map(|namespace| namespace.families.values())
                .map(|family| family.slots().count())
                .sum(),
        )
    }
    fn record_miss(&self) {
        self.state.lock().expect("local owner mutex").misses += 1;
    }
    #[pyo3(signature = (reason=None))]
    fn record_bypass(&self, py: Python<'_>, reason: Option<&Bound<'_, PyAny>>) -> PyResult<()> {
        let reasons = self.operation(py, REASONS);
        let index = if let Some(reason) = reason {
            reasons.call_method1("index", (reason,))?.extract()?
        } else {
            reasons.len()? - 1
        };
        self.state.lock().expect("local owner mutex").bypasses[index] += 1;
        Ok(())
    }
    fn record_oversized_bypass(&self) {
        self.state.lock().expect("local owner mutex").oversized += 1;
    }
    fn namespaces_for_database(&self, py: Python<'_>, database: &str) -> Vec<Py<PyAny>> {
        let state = self.state.lock().expect("local owner mutex");
        state
            .names
            .get(database)
            .map(|names| {
                names
                    .order
                    .iter()
                    .map(|id| state.namespaces[id].python.clone_ref(py))
                    .collect()
            })
            .unwrap_or_default()
    }
    fn has_namespace(&self, namespace: &Bound<'_, PyAny>) -> PyResult<bool> {
        let names = namespace_names(namespace)?;
        Ok(self
            .state
            .lock()
            .expect("local owner mutex")
            .namespace(&names.0, &names.1)
            .is_some())
    }
    fn can_register_namespace(&self, namespace: &Bound<'_, PyAny>) -> PyResult<bool> {
        let names = namespace_names(namespace)?;
        let state = self.state.lock().expect("local owner mutex");
        Ok(!state.closed
            && (state.namespace(&names.0, &names.1).is_some()
                || state.namespaces.len() < state.max_namespaces))
    }
    fn try_current_epoch(&self, namespace: &Bound<'_, PyAny>) -> PyResult<Option<u64>> {
        let names = namespace_names(namespace)?;
        let mut state = self.state.lock().expect("local owner mutex");
        Ok(state
            .register(namespace.py(), namespace, &names)
            .map(|id| state.namespaces[&id].epoch))
    }
    fn current_epoch(&self, namespace: &Bound<'_, PyAny>) -> PyResult<u64> {
        Ok(self.try_current_epoch(namespace)?.unwrap_or(0))
    }
    fn current_index_generation(
        &self,
        py: Python<'_>,
        namespace: &Bound<'_, PyAny>,
    ) -> PyResult<u64> {
        let names = namespace_names(namespace)?;
        let mut state = self.state.lock().expect("local owner mutex");
        self.active(py, &state)?;
        Ok(state
            .register(py, namespace, &names)
            .map(|id| state.namespaces[&id].index_generation)
            .unwrap_or(0))
    }
    fn record_index_change(&self, py: Python<'_>, namespace: &Bound<'_, PyAny>) -> PyResult<()> {
        let names = namespace_names(namespace)?;
        let mut state = self.state.lock().expect("local owner mutex");
        self.active(py, &state)?;
        if let Some(id) = state.register(py, namespace, &names) {
            let minimum = state.namespaces[&id].index_generation + 1;
            let generation = state.next_generation(minimum);
            let token = state.token();
            let namespace = state.namespaces.get_mut(&id).expect("index namespace");
            namespace.index_generation = generation;
            namespace.query_token = token;
            namespace.families.clear();
            state.changed();
        }
        Ok(())
    }
    fn clear_namespace(&self, py: Python<'_>, namespace: &Bound<'_, PyAny>) -> PyResult<()> {
        let names = namespace_names(namespace)?;
        let mut retired = Retired::default();
        {
            let mut state = self.state.lock().expect("local owner mutex");
            self.active(py, &state)?;
            if let Some(id) = state.register(py, namespace, &names) {
                state.bump(id, false, &mut retired);
            }
        }
        Ok(())
    }
    fn create_namespace(&self, py: Python<'_>, namespace: &Bound<'_, PyAny>) -> PyResult<()> {
        self.clear_namespace(py, namespace)
    }
    fn drop_namespace(&self, py: Python<'_>, namespace: &Bound<'_, PyAny>) -> PyResult<()> {
        let names = namespace_names(namespace)?;
        let mut retired = Retired::default();
        {
            let mut state = self.state.lock().expect("local owner mutex");
            self.active(py, &state)?;
            if let Some(id) = state.namespace(&names.0, &names.1) {
                state.bump(id, true, &mut retired);
            }
        }
        Ok(())
    }
    fn release_namespace_if_epoch_matches(
        &self,
        py: Python<'_>,
        namespace: &Bound<'_, PyAny>,
        epoch: u64,
    ) -> PyResult<bool> {
        let names = namespace_names(namespace)?;
        let mut retired = Retired::default();
        let mut state = self.state.lock().expect("local owner mutex");
        self.active(py, &state)?;
        let matches = state
            .namespace(&names.0, &names.1)
            .filter(|id| state.namespaces[id].epoch == epoch);
        if let Some(id) = matches {
            state.bump(id, true, &mut retired);
        }
        drop(state);
        Ok(matches.is_some())
    }
    fn invalidate_namespace_metadata_probe(&self, _namespace: &Bound<'_, PyAny>) {}
    fn invalidate_namespace_metadata_probes_for_database(&self, _database: &str) {}
    fn is_database_available(&self, database: &str) -> bool {
        self.state
            .lock()
            .expect("local owner mutex")
            .available(database)
            .0
    }
    #[pyo3(signature = (database, *, available))]
    fn set_database_available(&self, database: &str, available: bool) {
        let mut state = self.state.lock().expect("local owner mutex");
        let (current, generation) = state.available(database);
        if current != available {
            state
                .availability
                .insert(Arc::from(database), (available, generation + 1));
            state.changed();
        }
    }
    fn capture_namespace_generation(
        &self,
        py: Python<'_>,
        namespace: &Bound<'_, PyAny>,
    ) -> PyResult<Capture> {
        let names = namespace_names(namespace)?;
        let mut state = self.state.lock().expect("local owner mutex");
        self.active(py, &state)?;
        let availability = state.available(&names.0).1;
        let id = state.register(py, namespace, &names);
        let current = id.map(|id| &state.namespaces[&id]);
        Ok(Capture {
            state: self.state.clone(),
            namespace: current
                .map(|namespace| namespace.python.clone_ref(py))
                .unwrap_or_else(|| namespace.clone().unbind()),
            namespace_id: id,
            identity: None,
            owner: None,
            handle: None,
            generation: current
                .map(|namespace| (namespace.generation, namespace.index_generation))
                .unwrap_or((0, 0)),
            query_token: current.map(|namespace| namespace.query_token).unwrap_or(0),
            availability,
            released: AtomicBool::new(false),
        })
    }
    fn begin_identity_admission(
        &self,
        py: Python<'_>,
        namespace: &Bound<'_, PyAny>,
        identity: &Bound<'_, PyAny>,
    ) -> PyResult<Capture> {
        self.ensure_active(py)?;
        let key = self.canonical_identity(identity, true)?;
        let hash = key.hash()?;
        let names = namespace_names(namespace)?;
        loop {
            let (revision, namespace_id, pins) = {
                let mut state = self.state.lock().expect("local owner mutex");
                self.active(py, &state)?;
                let id = state.register(py, namespace, &names);
                (
                    state.revision,
                    id,
                    id.map(|id| state.meta_pins(py, id, hash))
                        .unwrap_or(MetaPins::Empty),
                )
            };
            let found = pins.matching(&key)?;
            // Allocation/GC may run Python finalizers, so prepare the handle
            // outside the mutex and revalidate before publishing its weak index.
            let (owner, weak) = if let Some(handle) = found {
                (Some(pins.owner(py, handle)), None)
            } else if let Some(namespace) = namespace_id {
                let (owner, weak) = self.prepare_identity_owner(py, namespace, &key)?;
                (Some(owner), Some(weak))
            } else {
                (None, None)
            };
            let mut state = self.state.lock().expect("local owner mutex");
            self.active(py, &state)?;
            if state.revision != revision {
                continue;
            }
            let availability = state.available(&names.0).1;
            let handle = namespace_id.map(|id| {
                found.unwrap_or_else(|| {
                    state.insert_identity(
                        id,
                        owner.as_ref().expect("prepared owner").bind(py),
                        weak.as_ref().expect("prepared weak index").bind(py),
                        hash,
                    )
                })
            });
            let identity_generation = handle
                .map(|handle| {
                    let identity = state.identity_mut(handle).expect("captured identity");
                    identity.captures += 1;
                    identity.generation
                })
                .unwrap_or(0);
            let current = namespace_id.map(|id| &state.namespaces[&id]);
            return Ok(Capture {
                state: self.state.clone(),
                namespace: current
                    .map(|namespace| namespace.python.clone_ref(py))
                    .unwrap_or_else(|| namespace.clone().unbind()),
                namespace_id,
                identity: Some(key.unbind()),
                owner,
                handle,
                generation: (
                    current.map(|namespace| namespace.epoch).unwrap_or(0),
                    identity_generation,
                ),
                query_token: current.map(|namespace| namespace.query_token).unwrap_or(0),
                availability,
                released: AtomicBool::new(false),
            });
        }
    }
    #[pyo3(signature = (capture, discriminator, value, *, codec_options=None, find_source=None))]
    fn admit_namespace(
        &self,
        py: Python<'_>,
        capture: &Capture,
        discriminator: &Bound<'_, PyAny>,
        value: &Bound<'_, PyAny>,
        codec_options: Option<&Bound<'_, PyAny>>,
        find_source: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        self.ensure_active(py)?;
        let Some(encoded) = self.encode(py, value, codec_options)? else {
            return self.outcome(py, UNENCODABLE);
        };
        self.outcome(
            py,
            self.admit_namespace_bytes(py, capture, discriminator, &encoded, find_source)?,
        )
    }
    #[pyo3(signature = (capture, discriminator, encoded, *, find_source=None))]
    fn admit_namespace_encoded(
        &self,
        py: Python<'_>,
        capture: &Capture,
        discriminator: &Bound<'_, PyAny>,
        encoded: &Bound<'_, PyBytes>,
        find_source: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        self.outcome(
            py,
            self.admit_namespace_bytes(py, capture, discriminator, encoded, find_source)?,
        )
    }
    #[pyo3(signature = (capture, read_shape, value, *, alias=None, codec_options=None))]
    fn admit_identity(
        &self,
        py: Python<'_>,
        capture: &Capture,
        read_shape: &Bound<'_, PyAny>,
        value: &Bound<'_, PyAny>,
        alias: Option<&Bound<'_, PyAny>>,
        codec_options: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        self.check_capture(capture)?;
        let _release = ReleaseCapture(capture);
        self.ensure_active(py)?;
        let Some(encoded) = self.encode(py, value, codec_options)? else {
            return self.outcome(py, UNENCODABLE);
        };
        self.outcome(
            py,
            self.admit_identity_bytes(py, capture, read_shape, &encoded, alias)?,
        )
    }
    #[pyo3(signature = (capture, read_shape, encoded, *, alias=None))]
    fn admit_identity_encoded(
        &self,
        py: Python<'_>,
        capture: &Capture,
        read_shape: &Bound<'_, PyAny>,
        encoded: &Bound<'_, PyBytes>,
        alias: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        self.check_capture(capture)?;
        let _release = ReleaseCapture(capture);
        self.outcome(
            py,
            self.admit_identity_bytes(py, capture, read_shape, encoded, alias)?,
        )
    }
    fn lookup_identity_encoded(
        &self,
        py: Python<'_>,
        namespace: &Bound<'_, PyAny>,
        identity: &Bound<'_, PyAny>,
        read_shape: &Bound<'_, PyAny>,
    ) -> PyResult<Option<Py<PyBytes>>> {
        let names = namespace_names(namespace)?;
        if !self.lookup_gate(py, &names.0)? {
            return Ok(None);
        }
        let identity = self.canonical_identity(identity, false)?;
        let shape = self.canonical(read_shape)?;
        Ok(
            match self.lookup(
                py,
                &names,
                Kind::Identity,
                Query::Identity(&identity, &shape),
                false,
            )? {
                Read::Hit(payload) => Some(payload),
                Read::Miss | Read::Bypass => None,
            },
        )
    }
    #[pyo3(signature = (namespace, identity, read_shape, *, codec_options=None))]
    fn lookup_identity(
        &self,
        py: Python<'_>,
        namespace: &Bound<'_, PyAny>,
        identity: &Bound<'_, PyAny>,
        read_shape: &Bound<'_, PyAny>,
        codec_options: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        match self.lookup_identity_encoded(py, namespace, identity, read_shape)? {
            Some(payload) => Ok(self
                .operation(py, DECODE)
                .call1((payload.bind(py), codec_options))?
                .unbind()),
            None => Ok(self.operations[MISS].clone_ref(py)),
        }
    }
    #[pyo3(signature = (namespace, discriminator, *, defer_miss=false))]
    fn lookup_namespace_encoded(
        &self,
        py: Python<'_>,
        namespace: &Bound<'_, PyAny>,
        discriminator: &Bound<'_, PyAny>,
        defer_miss: bool,
    ) -> PyResult<Py<PyAny>> {
        let names = namespace_names(namespace)?;
        if !self.lookup_gate(py, &names.0)? {
            return Ok(self.operations[MISS].clone_ref(py));
        }
        let key = self.canonical(discriminator)?;
        match self.lookup(py, &names, Kind::Namespace, Query::Plain(&key), defer_miss)? {
            Read::Hit(payload) => Ok(payload.into_any()),
            Read::Miss => {
                Ok(self.operations[if defer_miss { DEFERRED_MISS } else { MISS }].clone_ref(py))
            }
            Read::Bypass => Ok(self.operations[MISS].clone_ref(py)),
        }
    }
    #[pyo3(signature = (namespace, discriminator, *, codec_options=None, defer_miss=false))]
    fn lookup_namespace(
        &self,
        py: Python<'_>,
        namespace: &Bound<'_, PyAny>,
        discriminator: &Bound<'_, PyAny>,
        codec_options: Option<&Bound<'_, PyAny>>,
        defer_miss: bool,
    ) -> PyResult<Py<PyAny>> {
        let result = self.lookup_namespace_encoded(py, namespace, discriminator, defer_miss)?;
        if result.bind(py).is_instance_of::<PyBytes>() {
            Ok(self
                .operation(py, DECODE)
                .call1((result, codec_options))?
                .unbind())
        } else {
            Ok(result)
        }
    }
    fn resolve_alias(
        &self,
        py: Python<'_>,
        namespace: &Bound<'_, PyAny>,
        definition: &Bound<'_, PyAny>,
        value: &Bound<'_, PyAny>,
        collation: &Bound<'_, PyAny>,
    ) -> PyResult<Option<Py<PyAny>>> {
        let names = namespace_names(namespace)?;
        if !self.lookup_gate(py, &names.0)? {
            return Ok(None);
        }
        let key = self
            .operation(py, ALIAS_KEY)
            .call1((definition, value, collation))?;
        let hashes = Query::Plain(&key).hash()?;
        loop {
            let (revision, pins) = {
                let mut state = self.state.lock().expect("local owner mutex");
                self.active(py, &state)?;
                if !state.available(&names.0).0 {
                    let reason = state.unavailable_reason;
                    state.bypasses[reason] += 1;
                    return Ok(None);
                }
                let Some(id) = state.register(py, namespace, &names) else {
                    return Ok(None);
                };
                (
                    state.revision,
                    state.pins(py, id, Kind::Alias, scoped_hash(id, Kind::Alias, hashes)),
                )
            };
            let found = pins.matching(py, &Query::Plain(&key))?;
            let state = self.state.lock().expect("local owner mutex");
            self.active(py, &state)?;
            if state.revision != revision {
                continue;
            }
            return Ok(found.map(|pin| {
                let Body::Alias { identity, .. } = &pin.node.body else {
                    unreachable!("alias result")
                };
                identity.clone_ref(py)
            }));
        }
    }
    fn record_write(
        &self,
        py: Python<'_>,
        namespace: &Bound<'_, PyAny>,
        identity: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        self.ensure_active(py)?;
        let ordered = self.operation(py, ORDER_SENSITIVE).call1((identity,))?;
        let names = namespace_names(namespace)?;
        let id = {
            let mut state = self.state.lock().expect("local owner mutex");
            self.active(py, &state)?;
            let Some(id) = state.register(py, namespace, &names) else {
                return Ok(());
            };
            let token = state.token();
            let namespace = state.namespaces.get_mut(&id).expect("written namespace");
            namespace.generation += 1;
            namespace.query_token = token;
            namespace.families.clear();
            state.changed();
            id
        };
        let key = match self.canonical(&ordered) {
            Ok(key) => key,
            Err(error) if error.is_instance(py, self.operation(py, UNSUPPORTED_ERROR)) => {
                return Ok(());
            }
            Err(error) => return Err(error),
        };
        let hash = key.hash()?;
        loop {
            let (revision, pins) = {
                let state = self.state.lock().expect("local owner mutex");
                self.active(py, &state)?;
                if !state.namespaces.contains_key(&id) {
                    return Ok(());
                }
                (state.revision, state.meta_pins(py, id, hash))
            };
            let found = pins.matching(&key)?;
            let mut retired = Retired::default();
            let mut state = self.state.lock().expect("local owner mutex");
            self.active(py, &state)?;
            if state.revision != revision {
                continue;
            }
            if let Some(handle) = found {
                state
                    .identity_mut(handle)
                    .expect("written identity")
                    .generation += 1;
                state.clear_aliases(handle, &mut retired);
                state.changed();
            }
            drop(state);
            return Ok(());
        }
    }
    fn lookup_find_encoded(
        &self,
        py: Python<'_>,
        namespace: &Bound<'_, PyAny>,
        shape: &Bound<'_, PyAny>,
    ) -> PyResult<Option<Py<PyBytes>>> {
        let names = namespace_names(namespace)?;
        if !self.lookup_gate(py, &names.0)? {
            return Ok(None);
        }
        let prepared = if shape.is_instance(self.operation(py, PREPARED_FIND))? {
            shape.clone()
        } else {
            self.operation(py, PREPARED_FIND).call1((
                self.canonical(&shape.getattr("family")?)?,
                shape.getattr("limit")?,
            ))?
        };
        let key = prepared.getattr("discriminator")?;
        let hashes = Query::Plain(&key).hash()?;
        loop {
            let (revision, namespace_id, pins) = {
                let mut state = self.state.lock().expect("local owner mutex");
                self.active(py, &state)?;
                if !state.available(&names.0).0 {
                    let reason = state.unavailable_reason;
                    state.bypasses[reason] += 1;
                    return Ok(None);
                }
                let Some(id) = state.register(py, namespace, &names) else {
                    state.misses += 1;
                    return Ok(None);
                };
                (
                    state.revision,
                    id,
                    state.pins(
                        py,
                        id,
                        Kind::Namespace,
                        scoped_hash(id, Kind::Namespace, hashes),
                    ),
                )
            };
            let exact = pins.matching(py, &Query::Plain(&key))?;
            {
                let mut state = self.state.lock().expect("local owner mutex");
                self.active(py, &state)?;
                if state.revision != revision {
                    continue;
                }
                if let Some(pin) = exact.filter(|pin| state.valid(&pin.node)) {
                    state.touch(pin.slot);
                    state.hits += 1;
                    return Ok(Some(pin.node.payload().clone_ref(py)));
                }
            }
            // Prepare a covering-family probe only after an exact miss. The
            // ordinary exact hit hashes its prepared discriminator just once.
            let raw_limit = prepared.getattr("limit")?;
            let positive = !raw_limit.is_instance_of::<PyBool>() && raw_limit.gt(0)?;
            let limit = if positive {
                match raw_limit.extract::<u64>() {
                    Ok(limit) => Some(limit),
                    Err(error) if error.is_instance_of::<PyOverflowError>(py) => None,
                    Err(error) => return Err(error),
                }
            } else {
                None
            };
            let family = prepared.getattr("family")?;
            let family_hash = if positive { Some(family.hash()?) } else { None };
            let candidates = {
                let state = self.state.lock().expect("local owner mutex");
                self.active(py, &state)?;
                if state.revision != revision {
                    continue;
                }
                let mut candidates = Pins::Empty;
                for (source_limit, slot) in family_hash
                    .and_then(|hash| state.namespaces[&namespace_id].families.get(&hash))
                    .into_iter()
                    .flat_map(Family::slots)
                {
                    if source_limit == 0 || limit.is_some_and(|limit| source_limit >= limit) {
                        candidates.push(Pin {
                            slot,
                            node: state.node(slot).clone(),
                            _owner: None,
                        });
                    }
                }
                candidates
            };
            let mut found = None;
            for candidate in candidates.iter() {
                let source = candidate.node.source().expect("find family source");
                let source_key = self
                    .operation(py, FIND_KEY)
                    .call1((&family, source.limit))?;
                if Query::Plain(&source_key).matches(py, &candidate.node)? {
                    found = Some(candidate);
                    break;
                }
            }
            let mut state = self.state.lock().expect("local owner mutex");
            self.active(py, &state)?;
            if state.revision != revision {
                continue;
            }
            if let Some(pin) =
                found.filter(|pin| state.node_is_current(pin) && state.valid(&pin.node))
            {
                state.touch(pin.slot);
                state.hits += 1;
                return Ok(Some(pin.node.payload().clone_ref(py)));
            }
            state.misses += 1;
            return Ok(None);
        }
    }
    #[pyo3(signature = (namespace, shape, *, codec_options=None))]
    fn lookup_find(
        &self,
        py: Python<'_>,
        namespace: &Bound<'_, PyAny>,
        shape: &Bound<'_, PyAny>,
        codec_options: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        match self.lookup_find_encoded(py, namespace, shape)? {
            Some(payload) => Ok(self
                .operation(py, DECODE_FIND)
                .call1((payload.bind(py), shape.getattr("limit")?, codec_options))?
                .unbind()),
            None => Ok(self.operations[MISS].clone_ref(py)),
        }
    }
    fn discard_namespace_entry(
        &self,
        py: Python<'_>,
        capture: &Capture,
        discriminator: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        self.check_capture(capture)?;
        self.ensure_active(py)?;
        let key = self.canonical(discriminator)?;
        let hashes = Query::Plain(&key).hash()?;
        loop {
            let (revision, pins) = {
                let state = self.state.lock().expect("local owner mutex");
                self.active(py, &state)?;
                if !Self::namespace_capture_valid(&state, capture) {
                    return Ok(());
                }
                let id = capture.namespace_id.expect("valid capture");
                (
                    state.revision,
                    state.pins(
                        py,
                        id,
                        Kind::Namespace,
                        scoped_hash(id, Kind::Namespace, hashes),
                    ),
                )
            };
            let found = pins.matching(py, &Query::Plain(&key))?;
            let mut retired = Retired::default();
            let mut state = self.state.lock().expect("local owner mutex");
            self.active(py, &state)?;
            if state.revision != revision {
                continue;
            }
            if !Self::namespace_capture_valid(&state, capture) {
                return Ok(());
            }
            if let Some(pin) = found.filter(|pin| state.valid(&pin.node)) {
                state.remove_value(pin.slot, true, &mut retired);
            }
            state.cleanup_empty();
            drop(state);
            return Ok(());
        }
    }
    fn discard_stale_alias(
        &self,
        py: Python<'_>,
        capture: &Capture,
        alias: &Bound<'_, PyAny>,
        expected_identity: &Bound<'_, PyAny>,
    ) -> PyResult<()> {
        self.check_capture(capture)?;
        self.ensure_active(py)?;
        let hashes = Query::Plain(alias).hash()?;
        loop {
            let (revision, pins) = {
                let state = self.state.lock().expect("local owner mutex");
                self.active(py, &state)?;
                if !Self::namespace_capture_valid(&state, capture) {
                    return Ok(());
                }
                let id = capture.namespace_id.expect("valid capture");
                (
                    state.revision,
                    state.pins(py, id, Kind::Alias, scoped_hash(id, Kind::Alias, hashes)),
                )
            };
            let found = pins.matching(py, &Query::Plain(alias))?;
            let matches = if let Some(pin) = found {
                let Body::Alias { identity, .. } = &pin.node.body else {
                    unreachable!("alias candidate")
                };
                identity.bind(py).is(expected_identity)
                    || identity.bind(py).eq(expected_identity)?
            } else {
                false
            };
            let mut retired = Retired::default();
            let mut state = self.state.lock().expect("local owner mutex");
            self.active(py, &state)?;
            if state.revision != revision {
                continue;
            }
            if !Self::namespace_capture_valid(&state, capture) {
                return Ok(());
            }
            if matches {
                let pin = found.expect("matching alias");
                let Body::Alias { metadata, .. } = pin.node.body else {
                    unreachable!("alias candidate")
                };
                state.remove_alias(pin.slot, &mut retired);
                state.prune_identity(pin.node.namespace, metadata, &mut retired);
                state.cleanup_empty();
            }
            drop(state);
            return Ok(());
        }
    }
    #[pyo3(signature = (namespace_capture, discriminator, identity, read_shape, value, *, alias, codec_options=None))]
    #[allow(
        clippy::too_many_arguments,
        reason = "Python unique-read admission supplies both keys and codec options"
    )]
    fn admit_unique_key_match(
        &self,
        py: Python<'_>,
        namespace_capture: &Capture,
        discriminator: &Bound<'_, PyAny>,
        identity: &Bound<'_, PyAny>,
        read_shape: &Bound<'_, PyAny>,
        value: &Bound<'_, PyAny>,
        alias: &Bound<'_, PyAny>,
        codec_options: Option<&Bound<'_, PyAny>>,
    ) -> PyResult<Py<PyAny>> {
        let capture = namespace_capture;
        self.check_capture(capture)?;
        self.ensure_active(py)?;
        let identity = self.canonical_identity(identity, true)?;
        let Some(encoded) = self.encode(py, value, codec_options)? else {
            return self.outcome(py, UNENCODABLE);
        };
        let key = self.canonical(discriminator)?;
        let shape = self.canonical(read_shape)?;
        let identity_key = PyTuple::new(py, [&identity, &shape])?.into_any();
        let identity_hash = identity.hash()?;
        let namespace_hashes = Query::Plain(&key).hash()?;
        let identity_hashes = Query::Identity(&identity, &shape).hash()?;
        let alias_hashes = Query::Plain(alias).hash()?;
        let names = namespace_names(capture.namespace.bind(py))?;
        let weight = encoded.as_bytes().len();
        loop {
            let (revision, metadata_pins, ns_pins, id_pins, aliases, ns_hash, id_hash, alias_hash) = {
                let mut state = self.state.lock().expect("local owner mutex");
                self.active(py, &state)?;
                if let Some(outcome) = state.admission_gate(&names.0, capture.availability, weight)
                {
                    drop(state);
                    return self.outcome(py, outcome);
                }
                if !Self::namespace_capture_valid(&state, capture) {
                    drop(state);
                    return self.outcome(py, STALE);
                }
                let id = capture.namespace_id.expect("valid capture");
                let ns_hash = scoped_hash(id, Kind::Namespace, namespace_hashes);
                let id_hash = scoped_hash(id, Kind::Identity, identity_hashes);
                let alias_hash = scoped_hash(id, Kind::Alias, alias_hashes);
                (
                    state.revision,
                    state.meta_pins(py, id, identity_hash),
                    state.pins(py, id, Kind::Namespace, ns_hash),
                    state.pins(py, id, Kind::Identity, id_hash),
                    state.pins(py, id, Kind::Alias, alias_hash),
                    ns_hash,
                    id_hash,
                    alias_hash,
                )
            };
            let metadata = metadata_pins.matching(&identity)?;
            let (owner, weak) = if let Some(handle) = metadata {
                (metadata_pins.owner(py, handle), None)
            } else {
                let (owner, weak) = self.prepare_identity_owner(
                    py,
                    capture.namespace_id.expect("valid namespace capture"),
                    &identity,
                )?;
                (owner, Some(weak))
            };
            let previous_ns = ns_pins.matching(py, &Query::Plain(&key))?;
            let previous_id = id_pins.matching(py, &Query::Identity(&identity, &shape))?;
            let previous_alias = aliases.matching(py, &Query::Plain(alias))?;
            let mut retired = Retired::default();
            let mut state = self.state.lock().expect("local owner mutex");
            self.active(py, &state)?;
            if state.revision != revision {
                continue;
            }
            if !Self::namespace_capture_valid(&state, capture) {
                drop(state);
                return self.outcome(py, STALE);
            }
            let namespace = capture.namespace_id.expect("valid capture");
            let handle = metadata.unwrap_or_else(|| {
                state.insert_identity(
                    namespace,
                    owner.bind(py),
                    weak.as_ref().expect("prepared weak index").bind(py),
                    identity_hash,
                )
            });
            let metadata = state.identity_mut(handle).expect("unique identity");
            metadata.captures += 1;
            let generation = metadata.generation;
            let epoch = state.namespaces[&namespace].epoch;
            state.publish_alias(
                AliasPublication {
                    namespace,
                    hash: alias_hash,
                    key: alias,
                    identity: &identity,
                    metadata: handle,
                },
                previous_alias,
                &mut retired,
            );
            let token = state.token();
            let ns_node = Node {
                token,
                namespace,
                hash: ns_hash,
                key: key.clone().unbind(),
                body: Body::Namespace {
                    payload: encoded.clone().unbind(),
                    weight,
                    generation: capture.query_token,
                    source: None,
                },
            };
            let ns_result = state.put(py, ns_node, previous_ns, &mut retired);
            let token = state.token();
            let id_node = Node {
                token,
                namespace,
                hash: id_hash,
                key: identity_key.clone().unbind(),
                body: Body::Identity {
                    payload: encoded.clone().unbind(),
                    weight,
                    epoch,
                    identity: handle,
                    generation,
                },
            };
            let id_result = state.put(py, id_node, previous_id, &mut retired);
            let admitted = ns_result.is_some_and(|handle| state.resident(handle))
                && id_result.is_some_and(|handle| state.resident(handle));
            state
                .identity_mut(handle)
                .expect("reserved unique identity")
                .captures -= 1;
            state.prune_identity(namespace, handle, &mut retired);
            state.cleanup_empty();
            drop(state);
            return self.outcome(py, if admitted { ADMITTED } else { STALE });
        }
    }
    fn record_stream_poll(&self, py: Python<'_>, database: &str) -> PyResult<()> {
        self.stream_cost
            .bind(py)
            .call_method1("record_poll", (database,))?;
        Ok(())
    }
    fn record_logical_event_bytes(
        &self,
        py: Python<'_>,
        database: &str,
        count: u64,
    ) -> PyResult<()> {
        self.stream_cost
            .bind(py)
            .call_method1("record_logical_event_bytes", (database, count))?;
        Ok(())
    }
    fn record_invalidation_applied(
        &self,
        py: Python<'_>,
        database: &str,
        raw_lag_seconds: f64,
        wall_seconds: f64,
        monotonic_seconds: f64,
    ) -> PyResult<()> {
        self.stream_cost.bind(py).call_method1(
            "record_invalidation",
            (database, raw_lag_seconds, wall_seconds, monotonic_seconds),
        )?;
        Ok(())
    }
    #[pyo3(signature = (database=None))]
    fn reset_stream_cost_statistics(&self, py: Python<'_>, database: Option<&str>) -> PyResult<()> {
        match database {
            Some(database) => {
                self.stream_cost
                    .bind(py)
                    .call_method1("reset", (database,))?;
            }
            None => {
                self.stream_cost.bind(py).call_method0("reset_all")?;
            }
        }
        Ok(())
    }
    fn stream_cost_snapshot(&self, py: Python<'_>, database: &str) -> PyResult<Py<PyAny>> {
        let used = self.state.lock().expect("local owner mutex").used;
        let kwargs = PyDict::new(py);
        kwargs.set_item("resident_bytes", used)?;
        Ok(self
            .stream_cost
            .bind(py)
            .call_method("snapshot", (database,), Some(&kwargs))?
            .unbind())
    }
    fn active_stream_cost_databases(&self, py: Python<'_>) -> PyResult<Py<PyAny>> {
        Ok(self
            .stream_cost
            .bind(py)
            .call_method0("active_databases")?
            .unbind())
    }
    fn __traverse__(&self, visit: PyVisit<'_>) -> Result<(), PyTraverseError> {
        for operation in &self.operations {
            visit.call(operation)?;
        }
        visit.call(&self.config)?;
        visit.call(&self.stream_cost)?;
        let state = self.state.lock().expect("local owner mutex");
        for namespace in state.namespaces.values() {
            visit.call(&namespace.python)?;
        }
        for identity in state.identities.iter() {
            visit.call(&identity.owner)?;
            if let Some(owner) = &identity.resident_owner {
                visit.call(owner)?;
            }
        }
        for row in state.rows.iter() {
            match &row.node.body {
                Body::Namespace { payload, .. } | Body::Identity { payload, .. } => {
                    visit.call(&row.node.key)?;
                    visit.call(payload)?
                }
                // Each alias reference is traced once by its identity owner.
                Body::Alias { .. } => {}
            }
        }
        Ok(())
    }
    fn __clear__(&self) {
        self.close();
    }
}

#[pyfunction]
pub(crate) fn local_cache_type(py: Python<'_>) -> Bound<'_, PyType> {
    py.get_type::<LocalOwner>()
}
