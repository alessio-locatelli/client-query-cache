use std::collections::HashMap;

use crate::hash;
use crate::memory::{WORD_BYTES, Words};
use crate::sync::{AtomicU64, Ordering, fence};

const MAGIC: u64 = u64::from_le_bytes(*b"cqcsidx3");
const LAYOUT_VERSION: u64 = 3;

const H_MAGIC: usize = 0;
const H_VERSION: usize = 1;
const H_INCARNATION: usize = 2;
const H_SLOTS: usize = 3;
const H_ARENA_WORDS: usize = 4;
const H_DATABASES: usize = 5;
const H_NAMESPACES: usize = 6;
const H_EXPIRY_NS: usize = 7;
const H_CAPTURE_ENABLED: usize = 8;
const HEADER_WORDS: usize = 9;

const D_AVAILABLE: usize = 0;
const D_PROGRESS_NS: usize = 1;
const D_FENCE: usize = 2;
const DATABASE_WORDS: usize = 3;
const N_EPOCH: usize = 0;
const N_MUTATION: usize = 1;
const NAMESPACE_WORDS: usize = 2;

const S_VERSION: usize = 0;
const S_HASH: usize = 1;
const S_STATE: usize = 2;
const S_EPOCH: usize = 3;
const S_KEY_AT: usize = 4;
const S_PAYLOAD_AT: usize = 5;
const S_LENGTHS: usize = 6;
const S_TOKEN: usize = 7;
const SLOT_WORDS: usize = 8;
const SLOT_FIELDS: [usize; 7] = [
    S_HASH,
    S_STATE,
    S_EPOCH,
    S_KEY_AT,
    S_PAYLOAD_AT,
    S_LENGTHS,
    S_TOKEN,
];

const EMPTY: u64 = 0;
const OCCUPIED: u64 = 1;
const STATE_MASK: u64 = 0xff;
const NAMESPACE_SHIFT: u32 = 32;
const LENGTH_MASK: u64 = 0xffff_ffff;
const HIGH_SHIFT: u32 = 32;

const B_VERSION: usize = 0;
const B_LENGTH: usize = 1;
const BLOCK_HEADER_WORDS: usize = 2;
const EXACT_CLASS_WORDS: usize = 16;
const CLASSES_PER_DOUBLING: usize = 8;

const READ_ATTEMPTS: usize = 4;
const INLINE_KEY_BYTES: usize = 512;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) struct Layout {
    slots: usize,
    arena_words: usize,
    databases: usize,
    namespaces: usize,
}

impl Layout {
    pub(crate) fn new(
        slots: usize,
        arena_words: usize,
        databases: usize,
        namespaces: usize,
    ) -> Option<Self> {
        if !slots.is_power_of_two() || arena_words == 0 || databases == 0 || namespaces == 0 {
            return None;
        }
        u32::try_from(arena_words).ok()?;
        u32::try_from(namespaces).ok()?;
        let slots_start = databases
            .checked_mul(DATABASE_WORDS)?
            .checked_add(HEADER_WORDS)?
            .checked_add(namespaces.checked_mul(NAMESPACE_WORDS)?)?
            .checked_next_multiple_of(SLOT_WORDS)?;
        slots
            .checked_mul(SLOT_WORDS)?
            .checked_add(slots_start)?
            .checked_add(arena_words)?
            .checked_mul(WORD_BYTES)?;
        Some(Self {
            slots,
            arena_words,
            databases,
            namespaces,
        })
    }

    fn database_at(&self, database: usize) -> usize {
        HEADER_WORDS + database * DATABASE_WORDS
    }

    fn namespace_at(&self, namespace: usize) -> usize {
        HEADER_WORDS + self.databases * DATABASE_WORDS + namespace * NAMESPACE_WORDS
    }

    fn slot_at(&self, slot: usize) -> usize {
        self.namespace_at(self.namespaces)
            .next_multiple_of(SLOT_WORDS)
            + slot * SLOT_WORDS
    }

    fn arena_start(&self) -> usize {
        self.slot_at(self.slots)
    }

    pub(crate) fn words(&self) -> usize {
        self.arena_start() + self.arena_words
    }

    fn max_published(&self) -> usize {
        self.slots - self.slots / 4
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Miss {
    Incarnation,
    Range,
    Unavailable,
    Expired,
    Epoch,
    Absent,
    Contended,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Refusal {
    Entry,
    Dead,
    Arena,
    Slots,
}

pub(crate) struct Query<'q> {
    pub(crate) database: usize,
    pub(crate) namespace: usize,
    pub(crate) epoch: u64,
    pub(crate) identity: &'q [u8],
    pub(crate) shape: &'q [u8],
}

impl Query<'_> {
    fn key_len(&self) -> usize {
        self.identity.len() + self.shape.len()
    }

    fn hash(&self) -> u64 {
        hash::key(self.namespace as u64, self.identity, self.shape)
    }
}

#[derive(Debug)]
pub(crate) struct Located {
    slot: usize,
    version: u64,
    payload_at: usize,
    pub(crate) payload_len: usize,
    pub(crate) token: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub(crate) struct Block {
    pub(crate) at: usize,
    pub(crate) version: u64,
}

impl Block {
    pub(crate) fn token(self) -> u64 {
        (self.version << HIGH_SHIFT) | self.at as u64
    }
}

fn to_usize(value: u64) -> Option<usize> {
    usize::try_from(value).ok()
}

fn word_of(bytes: &[u8]) -> u64 {
    let mut word = [0_u8; WORD_BYTES];
    word[..bytes.len()].copy_from_slice(bytes);
    u64::from_ne_bytes(word)
}

fn copy_words(source: &[AtomicU64], destination: &mut [u8]) {
    for (chunk, word) in destination.chunks_mut(WORD_BYTES).zip(source) {
        let bytes = word.load(Ordering::Relaxed).to_ne_bytes();
        chunk.copy_from_slice(&bytes[..chunk.len()]);
    }
}

fn block_words(length: usize) -> usize {
    let words = BLOCK_HEADER_WORDS + length.div_ceil(WORD_BYTES);
    if words <= EXACT_CLASS_WORDS {
        return words;
    }
    let step = (1_usize << words.ilog2()) / CLASSES_PER_DOUBLING;
    words.next_multiple_of(step)
}

#[derive(Clone)]
pub(crate) struct Index<M> {
    memory: M,
    layout: Layout,
}

impl<M: Words> Index<M> {
    pub(crate) fn create(
        memory: M,
        layout: Layout,
        incarnation: u64,
        expiry_ns: u64,
    ) -> Option<Self> {
        if memory.words().len() < layout.words() {
            return None;
        }
        let index = Self { memory, layout };
        for (at, value) in [
            (H_VERSION, LAYOUT_VERSION),
            (H_INCARNATION, incarnation),
            (H_SLOTS, layout.slots as u64),
            (H_ARENA_WORDS, layout.arena_words as u64),
            (H_DATABASES, layout.databases as u64),
            (H_NAMESPACES, layout.namespaces as u64),
            (H_EXPIRY_NS, expiry_ns),
        ] {
            index.word(at).store(value, Ordering::Relaxed);
        }
        index.word(H_MAGIC).store(MAGIC, Ordering::Release);
        Some(index)
    }

    pub(crate) fn attach(memory: M) -> Option<Self> {
        let words = memory.words();
        if words.len() < HEADER_WORDS
            || words[H_MAGIC].load(Ordering::Acquire) != MAGIC
            || words[H_VERSION].load(Ordering::Relaxed) != LAYOUT_VERSION
        {
            return None;
        }
        let layout = Layout::new(
            to_usize(words[H_SLOTS].load(Ordering::Relaxed))?,
            to_usize(words[H_ARENA_WORDS].load(Ordering::Relaxed))?,
            to_usize(words[H_DATABASES].load(Ordering::Relaxed))?,
            to_usize(words[H_NAMESPACES].load(Ordering::Relaxed))?,
        )?;
        (layout.words() <= words.len()).then_some(Self { memory, layout })
    }

    fn word(&self, at: usize) -> &AtomicU64 {
        &self.memory.words()[at]
    }

    fn arena(&self, at: usize) -> &AtomicU64 {
        self.word(self.layout.arena_start() + at)
    }

    fn slot_word(&self, slot: usize, field: usize) -> &AtomicU64 {
        self.word(self.layout.slot_at(slot) + field)
    }

    fn arena_range(&self, at: u64, words: usize) -> Option<&[AtomicU64]> {
        let start = to_usize(at)?;
        let end = start.checked_add(words)?;
        if end > self.layout.arena_words {
            return None;
        }
        let base = self.layout.arena_start();
        self.memory.words().get(base + start..base + end)
    }

    pub(crate) fn incarnation(&self) -> u64 {
        self.word(H_INCARNATION).load(Ordering::Acquire)
    }

    fn database_word(&self, database: usize, field: usize) -> Option<&AtomicU64> {
        (database < self.layout.databases)
            .then(|| self.word(self.layout.database_at(database) + field))
    }

    fn namespace_word(&self, namespace: usize, field: usize) -> Option<&AtomicU64> {
        (namespace < self.layout.namespaces)
            .then(|| self.word(self.layout.namespace_at(namespace) + field))
    }

    pub(crate) fn set_available(&self, database: usize, available: bool) -> bool {
        self.database_word(database, D_AVAILABLE)
            .map(|word| {
                if word.swap(u64::from(available), Ordering::AcqRel) != u64::from(available) {
                    self.advance(self.database_word(database, D_FENCE).unwrap());
                }
            })
            .is_some()
    }

    pub(crate) fn set_progress(&self, database: usize, monotonic_ns: u64) -> bool {
        self.database_word(database, D_PROGRESS_NS)
            .map(|word| {
                let previous = word.load(Ordering::Acquire);
                if previous != 0
                    && monotonic_ns.saturating_sub(previous)
                        > self.word(H_EXPIRY_NS).load(Ordering::Relaxed)
                {
                    self.advance(self.database_word(database, D_FENCE).unwrap());
                }
                word.store(monotonic_ns, Ordering::Release);
            })
            .is_some()
    }

    pub(crate) fn set_epoch(&self, namespace: usize, epoch: u64) -> bool {
        self.namespace_word(namespace, N_EPOCH)
            .map(|word| word.store(epoch, Ordering::Release))
            .is_some()
    }

    #[allow(
        deprecated,
        reason = "fetch_update supports the declared Rust 1.85 MSRV"
    )]
    fn advance(&self, word: &AtomicU64) {
        let _ = word.fetch_update(Ordering::AcqRel, Ordering::Acquire, |value| {
            value.checked_add(1)
        });
    }

    pub(crate) fn record_write(&self, namespace: usize) -> bool {
        self.namespace_word(namespace, N_MUTATION)
            .map(|word| self.advance(word))
            .is_some()
    }

    pub(crate) fn enable_capture(&self, enabled: bool) {
        self.word(H_CAPTURE_ENABLED)
            .store(u64::from(enabled), Ordering::Release);
    }

    pub(crate) fn capture(
        &self,
        incarnation: u64,
        query: &Query<'_>,
        now_ns: u64,
    ) -> Option<(u64, u64, u64)> {
        if self.word(H_CAPTURE_ENABLED).load(Ordering::Acquire) == 0 {
            return None;
        }
        let mutation = self
            .namespace_word(query.namespace, N_MUTATION)?
            .load(Ordering::Acquire);
        let fence = self
            .database_word(query.database, D_FENCE)?
            .load(Ordering::Acquire);
        if mutation == u64::MAX || fence == u64::MAX {
            return None;
        }
        self.check(incarnation, query, now_ns).ok()?;
        Some((mutation, fence, now_ns))
    }

    pub(crate) fn validate_capture(
        &self,
        incarnation: u64,
        query: &Query<'_>,
        token: (u64, u64, u64),
        now_ns: u64,
        max_age_ns: u64,
    ) -> bool {
        let (mutation, fence, captured_ns) = token;
        captured_ns <= now_ns
            && now_ns - captured_ns < max_age_ns
            && self.capture(incarnation, query, now_ns) == Some((mutation, fence, now_ns))
    }

    fn check(&self, incarnation: u64, query: &Query<'_>, now_ns: u64) -> Result<(), Miss> {
        if self.incarnation() != incarnation {
            return Err(Miss::Incarnation);
        }
        let available = self
            .database_word(query.database, D_AVAILABLE)
            .ok_or(Miss::Range)?;
        if available.load(Ordering::Acquire) == 0 {
            return Err(Miss::Unavailable);
        }
        let progress = self
            .database_word(query.database, D_PROGRESS_NS)
            .ok_or(Miss::Range)?
            .load(Ordering::Acquire);
        if progress == 0
            || now_ns.saturating_sub(progress) > self.word(H_EXPIRY_NS).load(Ordering::Relaxed)
        {
            return Err(Miss::Expired);
        }
        let epoch = self
            .namespace_word(query.namespace, N_EPOCH)
            .ok_or(Miss::Range)?;
        if epoch.load(Ordering::Acquire) != query.epoch {
            return Err(Miss::Epoch);
        }
        Ok(())
    }

    fn key_matches(&self, stored: &[AtomicU64], query: &Query<'_>) -> bool {
        let length = query.key_len();
        let mut inline = [0_u8; INLINE_KEY_BYTES];
        let mut spilled = Vec::new();
        let expected: &mut [u8] = if length <= INLINE_KEY_BYTES {
            &mut inline[..length]
        } else {
            spilled.resize(length, 0);
            &mut spilled
        };
        expected[..query.identity.len()].copy_from_slice(query.identity);
        expected[query.identity.len()..].copy_from_slice(query.shape);
        stored
            .iter()
            .zip(expected.chunks(WORD_BYTES))
            .all(|(word, chunk)| word.load(Ordering::Relaxed) == word_of(chunk))
    }

    fn locate(&self, query: &Query<'_>) -> Result<Located, Miss> {
        let hash = query.hash();
        let key_len = query.key_len();
        let mask = self.layout.slots - 1;
        let mut contended = false;
        for probe in 0..self.layout.slots {
            let slot = (hash as usize).wrapping_add(probe) & mask;
            let version = self.slot_word(slot, S_VERSION).load(Ordering::Acquire);
            if version & 1 == 1 {
                contended = true;
                continue;
            }
            let state = self.slot_word(slot, S_STATE).load(Ordering::Relaxed);
            if state & STATE_MASK == EMPTY {
                break;
            }
            if self.slot_word(slot, S_HASH).load(Ordering::Relaxed) != hash
                || (state >> NAMESPACE_SHIFT) != query.namespace as u64
            {
                continue;
            }
            let lengths = self.slot_word(slot, S_LENGTHS).load(Ordering::Relaxed);
            if (lengths & LENGTH_MASK) != key_len as u64 {
                continue;
            }
            let payload_len = (lengths >> HIGH_SHIFT) as usize;
            let key_at = self.slot_word(slot, S_KEY_AT).load(Ordering::Relaxed);
            let payload_at = self.slot_word(slot, S_PAYLOAD_AT).load(Ordering::Relaxed);
            let (Some(key), Some(_payload)) = (
                self.arena_range(key_at, key_len.div_ceil(WORD_BYTES)),
                self.arena_range(payload_at, payload_len.div_ceil(WORD_BYTES)),
            ) else {
                contended = true;
                continue;
            };
            if !self.key_matches(key, query) {
                continue;
            }
            if self.slot_word(slot, S_EPOCH).load(Ordering::Relaxed) != query.epoch {
                return Err(Miss::Absent);
            }
            return Ok(Located {
                slot,
                version,
                payload_at: payload_at as usize,
                payload_len,
                token: self.slot_word(slot, S_TOKEN).load(Ordering::Relaxed),
            });
        }
        Err(if contended {
            Miss::Contended
        } else {
            Miss::Absent
        })
    }

    pub(crate) fn copy_payload(&self, located: &Located, destination: &mut [u8]) -> bool {
        if destination.len() != located.payload_len {
            return false;
        }
        let Some(source) = self.arena_range(
            located.payload_at as u64,
            located.payload_len.div_ceil(WORD_BYTES),
        ) else {
            return false;
        };
        copy_words(source, destination);
        true
    }

    fn validate(&self, located: &Located) -> bool {
        fence(Ordering::Acquire);
        self.slot_word(located.slot, S_VERSION)
            .load(Ordering::Relaxed)
            == located.version
    }

    pub(crate) fn read<T>(
        &self,
        incarnation: u64,
        query: &Query<'_>,
        now_ns: u64,
        mut copy: impl FnMut(&Located) -> Option<T>,
    ) -> Result<(T, u64), Miss> {
        self.check(incarnation, query, now_ns)?;
        for _ in 0..READ_ATTEMPTS {
            let located = match self.locate(query) {
                Ok(located) => located,
                Err(Miss::Contended) => continue,
                Err(miss) => return Err(miss),
            };
            match copy(&located) {
                Some(value) if self.validate(&located) => return Ok((value, located.token)),
                _ => {}
            }
        }
        Err(Miss::Contended)
    }

    fn block_version(&self, block: Block) -> Option<&AtomicU64> {
        self.arena_range(block.at as u64, BLOCK_HEADER_WORDS)
            .map(|header| &header[B_VERSION])
    }

    pub(crate) fn is_live(&self, block: Block) -> bool {
        self.block_version(block)
            .is_some_and(|version| version.load(Ordering::Acquire) == block.version)
    }

    pub(crate) fn snapshot_length(&self, block: Block) -> Option<usize> {
        let header = self.arena_range(block.at as u64, BLOCK_HEADER_WORDS)?;
        if header[B_VERSION].load(Ordering::Acquire) != block.version {
            return None;
        }
        let length = to_usize(header[B_LENGTH].load(Ordering::Relaxed))?;
        self.arena_range(
            (block.at + BLOCK_HEADER_WORDS) as u64,
            length.div_ceil(WORD_BYTES),
        )?;
        Some(length)
    }

    pub(crate) fn snapshot_into(&self, block: Block, destination: &mut [u8]) -> bool {
        let Some(source) = self.arena_range(
            (block.at + BLOCK_HEADER_WORDS) as u64,
            destination.len().div_ceil(WORD_BYTES),
        ) else {
            return false;
        };
        copy_words(source, destination);
        fence(Ordering::Acquire);
        self.block_version(block)
            .is_some_and(|version| version.load(Ordering::Relaxed) == block.version)
    }

    #[cfg(test)]
    pub(crate) fn snapshot(&self, block: Block) -> Option<Vec<u8>> {
        let length = self.snapshot_length(block)?;
        let mut copy = vec![0; length];
        self.snapshot_into(block, &mut copy).then_some(copy)
    }
}

struct Slot {
    hash: u64,
    state: u64,
    epoch: u64,
    key_at: u64,
    payload_at: u64,
    lengths: u64,
    token: u64,
}

const EMPTY_SLOT: Slot = Slot {
    hash: 0,
    state: EMPTY,
    epoch: 0,
    key_at: 0,
    payload_at: 0,
    lengths: 0,
    token: 0,
};

pub(crate) struct Writer<M> {
    index: Index<M>,
    cursor: usize,
    free: HashMap<usize, Vec<usize>>,
    published: HashMap<u64, usize>,
}

impl<M: Words> Writer<M> {
    pub(crate) fn new(index: Index<M>) -> Self {
        Self {
            index,
            cursor: 0,
            free: HashMap::new(),
            published: HashMap::new(),
        }
    }

    pub(crate) fn published(&self) -> usize {
        self.published.len()
    }

    fn allocate(&mut self, length: usize) -> Option<Block> {
        let words = block_words(length);
        let at = match self.free.get_mut(&words).and_then(Vec::pop) {
            Some(at) => at,
            None => {
                let end = self.cursor.checked_add(words)?;
                if end > self.index.layout.arena_words {
                    return None;
                }
                let at = self.cursor;
                self.cursor = end;
                at
            }
        };
        let version_word = self.index.arena(at + B_VERSION);
        let version = version_word.load(Ordering::Relaxed) + 1;
        version_word.store(version, Ordering::Relaxed);
        self.index
            .arena(at + B_LENGTH)
            .store(length as u64, Ordering::Relaxed);
        fence(Ordering::Release);
        Some(Block { at, version })
    }

    fn free_block(&mut self, block: Block) {
        let version = self.index.arena(block.at + B_VERSION);
        if version.load(Ordering::Relaxed) != block.version {
            return;
        }
        version.store(block.version + 1, Ordering::Relaxed);
        let length = self
            .index
            .arena(block.at + B_LENGTH)
            .load(Ordering::Relaxed) as usize;
        self.free
            .entry(block_words(length))
            .or_default()
            .push(block.at);
    }

    fn write_bytes(&self, at: usize, parts: &[&[u8]]) {
        let mut pending = Vec::with_capacity(WORD_BYTES);
        let mut offset = at;
        for byte in parts.iter().flat_map(|part| part.iter()) {
            pending.push(*byte);
            if pending.len() == WORD_BYTES {
                self.index
                    .arena(offset)
                    .store(word_of(&pending), Ordering::Relaxed);
                pending.clear();
                offset += 1;
            }
        }
        if !pending.is_empty() {
            self.index
                .arena(offset)
                .store(word_of(&pending), Ordering::Relaxed);
        }
    }

    pub(crate) fn store(&mut self, payload: &[u8]) -> Option<Block> {
        if payload.len() as u64 > LENGTH_MASK {
            return None;
        }
        let block = self.allocate(payload.len())?;
        self.write_bytes(block.at + BLOCK_HEADER_WORDS, &[payload]);
        Some(block)
    }

    pub(crate) fn release(&mut self, block: Block) {
        self.unpublish(block);
        self.free_block(block);
    }

    fn write_slot(&self, slot: usize, fields: &Slot) {
        let index = &self.index;
        let version = index.slot_word(slot, S_VERSION);
        let previous = version.load(Ordering::Relaxed);
        version.store(previous + 1, Ordering::Relaxed);
        fence(Ordering::Release);
        for (field, value) in SLOT_FIELDS.into_iter().zip([
            fields.hash,
            fields.state,
            fields.epoch,
            fields.key_at,
            fields.payload_at,
            fields.lengths,
            fields.token,
        ]) {
            index.slot_word(slot, field).store(value, Ordering::Relaxed);
        }
        version.store(previous + 2, Ordering::Release);
    }

    fn read_slot(&self, slot: usize) -> Slot {
        let field = |field| self.index.slot_word(slot, field).load(Ordering::Relaxed);
        Slot {
            hash: field(S_HASH),
            state: field(S_STATE),
            epoch: field(S_EPOCH),
            key_at: field(S_KEY_AT),
            payload_at: field(S_PAYLOAD_AT),
            lengths: field(S_LENGTHS),
            token: field(S_TOKEN),
        }
    }

    fn free_key(&mut self, slot: &Slot) {
        let at = slot.key_at as usize - BLOCK_HEADER_WORDS;
        let version = self.index.arena(at + B_VERSION).load(Ordering::Relaxed);
        self.free_block(Block { at, version });
    }

    fn find_slot(&self, hash: u64, query: &Query<'_>) -> Option<usize> {
        let index = &self.index;
        let mask = index.layout.slots - 1;
        for probe in 0..index.layout.slots {
            let slot = (hash as usize).wrapping_add(probe) & mask;
            let fields = self.read_slot(slot);
            if fields.state & STATE_MASK == EMPTY {
                return Some(slot);
            }
            if fields.hash == hash
                && (fields.state >> NAMESPACE_SHIFT) == query.namespace as u64
                && (fields.lengths & LENGTH_MASK) == query.key_len() as u64
                && index
                    .arena_range(fields.key_at, query.key_len().div_ceil(WORD_BYTES))
                    .is_some_and(|key| index.key_matches(key, query))
            {
                return Some(slot);
            }
        }
        None
    }

    pub(crate) fn publish(&mut self, query: &Query<'_>, payload: Block) -> Result<u64, Refusal> {
        let key_len = query.key_len();
        if key_len as u64 > LENGTH_MASK || query.namespace >= self.index.layout.namespaces {
            return Err(Refusal::Entry);
        }
        if !self.index.is_live(payload) {
            return Err(Refusal::Dead);
        }
        let token = payload.token();
        if self.published.contains_key(&token) {
            return Ok(token);
        }
        if self.published.len() >= self.index.layout.max_published() {
            return Err(Refusal::Slots);
        }
        let hash = query.hash();
        let slot = self.find_slot(hash, query).ok_or(Refusal::Slots)?;
        let key = self.allocate(key_len).ok_or(Refusal::Arena)?;
        self.write_bytes(key.at + BLOCK_HEADER_WORDS, &[query.identity, query.shape]);
        let payload_len = self
            .index
            .arena(payload.at + B_LENGTH)
            .load(Ordering::Relaxed);
        let previous = self.read_slot(slot);
        if previous.state & STATE_MASK == OCCUPIED {
            self.published.remove(&previous.token);
            self.free_key(&previous);
        }
        self.write_slot(
            slot,
            &Slot {
                hash,
                state: OCCUPIED | ((query.namespace as u64) << NAMESPACE_SHIFT),
                epoch: query.epoch,
                key_at: (key.at + BLOCK_HEADER_WORDS) as u64,
                payload_at: (payload.at + BLOCK_HEADER_WORDS) as u64,
                lengths: key_len as u64 | (payload_len << HIGH_SHIFT),
                token,
            },
        );
        self.published.insert(token, slot);
        Ok(token)
    }

    pub(crate) fn unpublish(&mut self, payload: Block) -> bool {
        let Some(slot) = self.published.remove(&payload.token()) else {
            return false;
        };
        let removed = self.read_slot(slot);
        self.delete(slot);
        self.free_key(&removed);
        true
    }

    fn delete(&mut self, mut hole: usize) {
        let mask = self.index.layout.slots - 1;
        let mut next = hole;
        loop {
            next = (next + 1) & mask;
            let candidate = self.read_slot(next);
            if candidate.state & STATE_MASK == EMPTY {
                break;
            }
            let home = candidate.hash as usize & mask;
            let stays = if hole <= next {
                hole < home && home <= next
            } else {
                hole < home || home <= next
            };
            if stays {
                continue;
            }
            self.write_slot(hole, &candidate);
            self.published.insert(candidate.token, hole);
            hole = next;
        }
        self.write_slot(hole, &EMPTY_SLOT);
    }
}

#[cfg(all(test, not(loom)))]
mod tests {
    use std::sync::Arc;

    use super::*;
    use crate::memory::zeroed;

    const INCARNATION: u64 = 41;
    const EXPIRY_NS: u64 = 3_000_000_000;
    const NOW_NS: u64 = 10_000_000_000;
    const EPOCH: u64 = 7;

    type Memory = Arc<[AtomicU64]>;

    fn sized_fixture(slots: usize, arena_words: usize) -> (Index<Memory>, Writer<Memory>) {
        let layout = Layout::new(slots, arena_words, 2, 2).unwrap();
        let index = Index::create(zeroed(layout.words()), layout, INCARNATION, EXPIRY_NS).unwrap();
        assert!(index.set_available(0, true));
        assert!(index.set_progress(0, NOW_NS));
        assert!(index.set_epoch(1, EPOCH));
        let writer = Writer::new(index.clone());
        (index, writer)
    }

    fn fixture() -> (Index<Memory>, Writer<Memory>) {
        sized_fixture(8, 256)
    }

    fn query<'q>(identity: &'q [u8]) -> Query<'q> {
        Query {
            database: 0,
            namespace: 1,
            epoch: EPOCH,
            identity,
            shape: b"find_one",
        }
    }

    fn read(index: &Index<Memory>, query: &Query<'_>) -> Result<(Vec<u8>, u64), Miss> {
        index.read(INCARNATION, query, NOW_NS, |located| {
            let mut copy = vec![0; located.payload_len];
            index.copy_payload(located, &mut copy).then_some(copy)
        })
    }

    fn publish(writer: &mut Writer<Memory>, identity: &[u8], payload: &[u8]) -> Block {
        let block = writer.store(payload).unwrap();
        writer.publish(&query(identity), block).unwrap();
        block
    }

    fn only_slot(writer: &Writer<Memory>) -> usize {
        *writer.published.values().next().unwrap()
    }

    #[test]
    fn reads_a_published_entry() {
        let (index, mut writer) = fixture();
        let block = publish(&mut writer, b"identity", b"payload bytes");
        assert_eq!(
            read(&index, &query(b"identity")),
            Ok((b"payload bytes".to_vec(), block.token()))
        );
        assert_eq!(read(&index, &query(b"other")), Err(Miss::Absent));
    }

    #[test]
    fn local_captures_require_opt_in_and_current_validity() {
        let (index, _) = fixture();
        let q = query(b"uncached");
        assert_eq!(index.capture(INCARNATION, &q, NOW_NS), None);
        index.enable_capture(true);
        let token = index.capture(INCARNATION, &q, NOW_NS).unwrap();
        assert!(index.validate_capture(INCARNATION, &q, token, NOW_NS + 1, EXPIRY_NS));
        assert!(!index.validate_capture(INCARNATION + 1, &q, token, NOW_NS + 1, EXPIRY_NS));
        assert!(!index.validate_capture(INCARNATION, &q, token, NOW_NS - 1, EXPIRY_NS));
        assert!(!index.validate_capture(INCARNATION, &q, token, NOW_NS + EXPIRY_NS, EXPIRY_NS));
        assert!(index.record_write(q.namespace));
        assert!(!index.validate_capture(INCARNATION, &q, token, NOW_NS + 1, EXPIRY_NS));
        assert!(!index.record_write(index.layout.namespaces));
        let token = index.capture(INCARNATION, &q, NOW_NS).unwrap();
        index.set_epoch(q.namespace, EPOCH + 1);
        assert!(!index.validate_capture(INCARNATION, &q, token, NOW_NS, EXPIRY_NS));
    }

    #[test]
    fn recovery_never_revives_obsolete_captures() {
        let (index, _) = fixture();
        index.enable_capture(true);
        let q = query(b"uncached");
        let token = index.capture(INCARNATION, &q, NOW_NS).unwrap();
        index.set_available(q.database, false);
        assert_eq!(index.capture(INCARNATION, &q, NOW_NS), None);
        index.set_available(q.database, true);
        assert!(!index.validate_capture(INCARNATION, &q, token, NOW_NS, EXPIRY_NS));
        let token = index.capture(INCARNATION, &q, NOW_NS).unwrap();
        index.set_progress(q.database, NOW_NS + EXPIRY_NS + 1);
        assert!(!index.validate_capture(
            INCARNATION,
            &q,
            token,
            NOW_NS + EXPIRY_NS + 1,
            EXPIRY_NS * 10
        ));
        assert!(
            index
                .capture(INCARNATION, &q, NOW_NS + EXPIRY_NS + 1)
                .is_some()
        );
    }

    #[test]
    fn exhausted_capture_serials_fail_closed() {
        let (index, _) = fixture();
        index.enable_capture(true);
        for word in [
            index.namespace_word(1, N_MUTATION).unwrap(),
            index.database_word(0, D_FENCE).unwrap(),
        ] {
            word.store(u64::MAX - 1, Ordering::Release);
            index.advance(word);
            index.advance(word);
            assert_eq!(word.load(Ordering::Acquire), u64::MAX);
            assert_eq!(
                index.capture(INCARNATION, &query(b"uncached"), NOW_NS),
                None
            );
            word.store(0, Ordering::Release);
        }
    }

    #[test]
    fn rejects_reads_that_fail_a_validity_check() {
        let (index, mut writer) = fixture();
        publish(&mut writer, b"identity", b"payload");
        let cases: [(u64, Query<'_>, Miss); 5] = [
            (INCARNATION + 1, query(b"identity"), Miss::Incarnation),
            (
                INCARNATION,
                Query {
                    database: 2,
                    ..query(b"identity")
                },
                Miss::Range,
            ),
            (
                INCARNATION,
                Query {
                    namespace: 2,
                    ..query(b"identity")
                },
                Miss::Range,
            ),
            (
                INCARNATION,
                Query {
                    database: 1,
                    ..query(b"identity")
                },
                Miss::Unavailable,
            ),
            (
                INCARNATION,
                Query {
                    epoch: EPOCH + 1,
                    ..query(b"identity")
                },
                Miss::Epoch,
            ),
        ];
        for (incarnation, query, expected) in cases {
            let outcome = index.read(incarnation, &query, NOW_NS, |_| Some(()));
            assert_eq!(outcome.map(|_| ()), Err(expected));
        }
        assert!(index.set_progress(0, NOW_NS - EXPIRY_NS - 1));
        let outcome = index.read(INCARNATION, &query(b"identity"), NOW_NS, |_| Some(()));
        assert_eq!(outcome.map(|_| ()), Err(Miss::Expired));
    }

    #[test]
    fn treats_entries_from_an_older_epoch_as_absent() {
        let (index, mut writer) = fixture();
        publish(&mut writer, b"identity", b"payload");
        assert!(index.set_epoch(1, EPOCH + 1));
        let current = Query {
            epoch: EPOCH + 1,
            ..query(b"identity")
        };
        assert_eq!(read(&index, &current), Err(Miss::Absent));
    }

    #[test]
    fn locations_outside_the_arena_are_never_copied() {
        let (index, mut writer) = fixture();
        publish(&mut writer, b"identity", b"payload");
        let slot = only_slot(&writer);
        for (field, value) in [
            (S_PAYLOAD_AT, index.layout.arena_words as u64),
            (S_PAYLOAD_AT, u64::MAX),
            (S_KEY_AT, u64::MAX - 1),
            (S_LENGTHS, 16 | (u64::from(u32::MAX) << HIGH_SHIFT)),
        ] {
            let word = index.slot_word(slot, field);
            let original = word.swap(value, Ordering::Relaxed);
            let outcome = index.read(
                INCARNATION,
                &query(b"identity"),
                NOW_NS,
                |_| -> Option<()> { panic!("an out-of-range location reached the copy") },
            );
            assert!(matches!(outcome, Err(Miss::Contended | Miss::Absent)));
            word.store(original, Ordering::Relaxed);
        }
    }

    #[test]
    fn copies_require_the_located_length() {
        let (index, mut writer) = fixture();
        publish(&mut writer, b"identity", b"payload");
        let located = index.locate(&query(b"identity")).unwrap();
        assert!(!index.copy_payload(&located, &mut [0; 3]));
    }

    #[test]
    fn a_write_between_locate_and_validate_rejects_the_copy() {
        let (index, mut writer) = fixture();
        let first = publish(&mut writer, b"identity", b"first");
        let located = index.locate(&query(b"identity")).unwrap();
        writer.release(first);
        publish(&mut writer, b"identity", b"other");
        assert!(!index.validate(&located));
    }

    #[test]
    fn a_slot_left_mid_write_is_contended() {
        let (index, mut writer) = fixture();
        publish(&mut writer, b"identity", b"payload");
        index
            .slot_word(only_slot(&writer), S_VERSION)
            .fetch_add(1, Ordering::Relaxed);
        assert_eq!(read(&index, &query(b"identity")), Err(Miss::Contended));
    }

    #[test]
    fn publishing_a_dead_token_does_nothing() {
        let (index, mut writer) = fixture();
        let block = writer.store(b"payload").unwrap();
        writer.release(block);
        assert_eq!(
            writer.publish(&query(b"identity"), block),
            Err(Refusal::Dead)
        );
        assert_eq!(writer.published(), 0);
        assert_eq!(read(&index, &query(b"identity")), Err(Miss::Absent));
    }

    #[test]
    fn republishing_a_live_token_keeps_its_slot() {
        let (_index, mut writer) = fixture();
        let block = publish(&mut writer, b"identity", b"payload");
        assert_eq!(
            writer.publish(&query(b"identity"), block),
            Ok(block.token())
        );
        assert_eq!(writer.published(), 1);
    }

    #[test]
    fn publishing_a_resident_key_replaces_its_slot() {
        let (index, mut writer) = fixture();
        let first = publish(&mut writer, b"identity", b"first");
        let second = publish(&mut writer, b"identity", b"second");
        assert_eq!(writer.published(), 1);
        assert!(!writer.unpublish(first));
        assert_eq!(
            read(&index, &query(b"identity")),
            Ok((b"second".to_vec(), second.token()))
        );
    }

    #[test]
    fn releasing_a_published_payload_unpublishes_it() {
        let (index, mut writer) = fixture();
        let block = publish(&mut writer, b"identity", b"payload");
        writer.release(block);
        assert_eq!(read(&index, &query(b"identity")), Err(Miss::Absent));
        assert!(!writer.unpublish(block));
    }

    #[test]
    fn deletions_keep_colliding_keys_reachable() {
        let (index, mut writer) = sized_fixture(16, 1024);
        let identities: Vec<Vec<u8>> = (0..10_u8).map(|identity| vec![identity; 9]).collect();
        let blocks: Vec<Block> = identities
            .iter()
            .map(|identity| publish(&mut writer, identity, identity))
            .collect();
        for block in blocks.iter().step_by(2) {
            assert!(writer.unpublish(*block));
        }
        for (offset, identity) in identities.iter().enumerate() {
            let expected = if offset % 2 == 0 {
                Err(Miss::Absent)
            } else {
                Ok(identity.clone())
            };
            assert_eq!(
                read(&index, &query(identity)).map(|(payload, _)| payload),
                expected
            );
        }
        for block in blocks.iter().skip(1).step_by(2) {
            assert!(writer.unpublish(*block));
        }
        assert!((0..16).all(|slot| writer.read_slot(slot).state == EMPTY));
    }

    #[test]
    fn freed_blocks_are_reused_by_their_size_class() {
        let (_index, mut writer) = fixture();
        let first = writer.store(&[1; 40]).unwrap();
        writer.release(first);
        let second = writer.store(&[2; 36]).unwrap();
        assert_eq!(second.at, first.at);
        assert_eq!(second.version, first.version + 2);
        assert_eq!(block_words(4_371), 576);
    }

    #[test]
    fn snapshots_detect_free_and_reuse() {
        let (index, mut writer) = fixture();
        let first = writer.store(b"first payload").unwrap();
        assert_eq!(index.snapshot(first), Some(b"first payload".to_vec()));
        writer.release(first);
        assert_eq!(index.snapshot(first), None);
        let reused = writer.store(b"other payload").unwrap();
        assert_eq!(reused.at, first.at);
        assert_eq!(index.snapshot(first), None);
        assert_eq!(index.snapshot(reused), Some(b"other payload".to_vec()));
    }

    #[test]
    fn exhausted_capacity_is_reported() {
        let (_index, mut writer) = sized_fixture(8, 64);
        assert_eq!(writer.store(&[0; 1024]), None);
        let blocks: Vec<Block> = (0..7_u8)
            .map(|identity| writer.store(&[identity]).unwrap())
            .collect();
        for (identity, block) in (0..6_u8).zip(&blocks) {
            assert!(writer.publish(&query(&[identity]), *block).is_ok());
        }
        assert_eq!(
            writer.publish(&query(b"seventh"), blocks[6]),
            Err(Refusal::Slots)
        );
        let (_index, mut writer) = sized_fixture(8, 6);
        let block = writer.store(b"payload").unwrap();
        assert_eq!(
            writer.publish(&query(b"identity"), block),
            Err(Refusal::Arena)
        );
    }

    #[test]
    fn concurrent_rewrites_never_yield_mixed_payloads() {
        const ROUNDS: u64 = 20_000;
        let (index, mut writer) = sized_fixture(8, 64);
        let payloads = [vec![b'a'; 40], vec![b'b'; 40]];
        let observed = std::thread::scope(|scope| {
            let handle = scope.spawn(|| {
                (0..ROUNDS)
                    .filter_map(|_| read(&index, &query(b"identity")).ok())
                    .collect::<Vec<_>>()
            });
            let mut current = None;
            for round in 0..ROUNDS {
                if let Some(block) = current.take() {
                    writer.release(block);
                }
                current = Some(publish(
                    &mut writer,
                    b"identity",
                    &payloads[(round % 2) as usize],
                ));
            }
            handle.join().unwrap()
        });
        assert!(
            observed
                .iter()
                .all(|(payload, _)| payloads.contains(payload))
        );
    }

    #[test]
    fn attaches_only_to_a_complete_layout() {
        let (index, _writer) = fixture();
        assert_eq!(
            Index::attach(index.memory.clone()).unwrap().layout,
            index.layout
        );
        let truncated: Memory = zeroed(index.layout.words() - 1);
        for (target, source) in truncated.iter().zip(index.memory.iter()) {
            target.store(source.load(Ordering::Relaxed), Ordering::Relaxed);
        }
        assert!(Index::attach(truncated).is_none());
        assert!(Index::attach(zeroed(HEADER_WORDS)).is_none());
    }
}

#[cfg(all(test, loom))]
mod models {
    use std::sync::Arc;

    use loom::model::Builder;

    use super::*;
    use crate::memory::zeroed;

    const EPOCH: u64 = 1;

    fn query<'q>(identity: &'q [u8]) -> Query<'q> {
        Query {
            database: 0,
            namespace: 0,
            epoch: EPOCH,
            identity,
            shape: b"",
        }
    }

    fn fixture() -> (Index<Arc<[AtomicU64]>>, Writer<Arc<[AtomicU64]>>) {
        let layout = Layout::new(2, 16, 1, 1).unwrap();
        let index = Index::create(zeroed(layout.words()), layout, 1, u64::MAX).unwrap();
        index.set_available(0, true);
        index.set_progress(0, 1);
        index.set_epoch(0, EPOCH);
        let writer = Writer::new(index.clone());
        (index, writer)
    }

    fn model(test: impl Fn() + Send + Sync + 'static) {
        let mut builder = Builder::new();
        builder.preemption_bound = Some(2);
        builder.check(test);
    }

    #[test]
    fn reads_never_mix_published_and_reused_payloads() {
        model(|| {
            let (index, mut writer) = fixture();
            let first = writer.store(&[1; 16]).unwrap();
            writer.publish(&query(b"k"), first).unwrap();
            let reader = loom::thread::spawn(move || {
                index
                    .read(1, &query(b"k"), 1, |located| {
                        let mut copy = vec![0; located.payload_len];
                        index.copy_payload(located, &mut copy).then_some(copy)
                    })
                    .ok()
            });
            writer.release(first);
            let second = writer.store(&[2; 16]).unwrap();
            writer.publish(&query(b"k"), second).unwrap();
            if let Some((payload, _token)) = reader.join().unwrap() {
                assert!(payload == [1; 16] || payload == [2; 16]);
            }
        });
    }

    #[test]
    fn snapshots_never_return_a_reused_block() {
        model(|| {
            let (index, mut writer) = fixture();
            let first = writer.store(&[1; 16]).unwrap();
            let reader = loom::thread::spawn(move || index.snapshot(first));
            writer.release(first);
            writer.store(&[2; 16]).unwrap();
            if let Some(payload) = reader.join().unwrap() {
                assert_eq!(payload, [1; 16]);
            }
        });
    }

    #[test]
    fn completed_mutations_fence_captured_misses() {
        for availability in [false, true] {
            model(move || {
                let (index, _) = fixture();
                index.enable_capture(true);
                let token = index.capture(1, &query(b"uncached"), 1).unwrap();
                let changed = index.clone();
                let writer = loom::thread::spawn(move || {
                    if availability {
                        changed.set_available(0, false);
                        changed.set_available(0, true);
                    } else {
                        changed.record_write(0);
                    }
                });
                let reader = index.clone();
                let capture =
                    loom::thread::spawn(move || reader.capture(1, &query(b"uncached"), 1));
                writer.join().unwrap();
                capture.join().unwrap();
                assert!(!index.validate_capture(1, &query(b"uncached"), token, 1, u64::MAX));
            });
        }
    }

    #[test]
    fn progress_recovery_fences_earlier_misses() {
        model(|| {
            let (index, _) = fixture();
            index.word(H_EXPIRY_NS).store(1, Ordering::Release);
            index.enable_capture(true);
            let token = index.capture(1, &query(b"uncached"), 1).unwrap();
            let resumed = index.clone();
            let writer = loom::thread::spawn(move || {
                resumed.set_progress(0, 3);
            });
            let reader = index.clone();
            let capture = loom::thread::spawn(move || reader.capture(1, &query(b"uncached"), 3));
            writer.join().unwrap();
            capture.join().unwrap();
            assert!(!index.validate_capture(1, &query(b"uncached"), token, 3, u64::MAX));
        });
    }
}
