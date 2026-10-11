use crate::hash;
use crate::memory::{WORD_BYTES, Words};
use crate::sync::{AtomicU64, Ordering, fence};

const MAGIC: u64 = u64::from_le_bytes(*b"cqcsidx1");
const LAYOUT_VERSION: u64 = 1;

const H_MAGIC: usize = 0;
const H_VERSION: usize = 1;
const H_INCARNATION: usize = 2;
const H_SLOTS: usize = 3;
const H_ARENA_WORDS: usize = 4;
const H_DATABASES: usize = 5;
const H_NAMESPACES: usize = 6;
const H_EXPIRY_NS: usize = 7;
const HEADER_WORDS: usize = 8;

const D_AVAILABLE: usize = 0;
const D_PROGRESS_NS: usize = 1;
const DATABASE_WORDS: usize = 2;

const S_VERSION: usize = 0;
const S_HASH: usize = 1;
const S_STATE: usize = 2;
const S_EPOCH: usize = 3;
const S_OFFSET: usize = 4;
const S_LENGTHS: usize = 5;
const S_TOKEN: usize = 6;
const SLOT_WORDS: usize = 8;

const EMPTY: u64 = 0;
const OCCUPIED: u64 = 1;
const STATE_MASK: u64 = 0xff;
const NAMESPACE_SHIFT: u32 = 32;
const LENGTH_MASK: u64 = 0xffff_ffff;
const PAYLOAD_SHIFT: u32 = 32;

const READ_ATTEMPTS: usize = 4;
const INLINE_KEY_BYTES: usize = 256;

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
        let layout = Self {
            slots,
            arena_words,
            databases,
            namespaces,
        };
        let slots_start = databases
            .checked_mul(DATABASE_WORDS)?
            .checked_add(HEADER_WORDS)?
            .checked_add(namespaces)?
            .checked_next_multiple_of(SLOT_WORDS)?;
        slots
            .checked_mul(SLOT_WORDS)?
            .checked_add(slots_start)?
            .checked_add(arena_words)?
            .checked_mul(WORD_BYTES)?;
        Some(layout)
    }

    fn database_at(&self, database: usize) -> usize {
        HEADER_WORDS + database * DATABASE_WORDS
    }

    fn namespace_at(&self, namespace: usize) -> usize {
        HEADER_WORDS + self.databases * DATABASE_WORDS + namespace
    }

    fn slots_start(&self) -> usize {
        self.namespace_at(self.namespaces)
            .next_multiple_of(SLOT_WORDS)
    }

    fn slot_at(&self, slot: usize) -> usize {
        self.slots_start() + slot * SLOT_WORDS
    }

    fn arena_start(&self) -> usize {
        self.slot_at(self.slots)
    }

    pub(crate) fn words(&self) -> usize {
        self.arena_start() + self.arena_words
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
}

#[derive(Debug)]
pub(crate) struct Located {
    slot: usize,
    version: u64,
    payload_at: usize,
    pub(crate) payload_len: usize,
    pub(crate) token: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Full {
    Entry,
    Arena,
    Slots,
}

#[derive(Clone)]
pub(crate) struct Index<M> {
    memory: M,
    layout: Layout,
}

fn to_usize(value: u64) -> Option<usize> {
    usize::try_from(value).ok()
}

fn word_of(bytes: &[u8]) -> u64 {
    let mut word = [0_u8; WORD_BYTES];
    word[..bytes.len()].copy_from_slice(bytes);
    u64::from_ne_bytes(word)
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

    fn word(&self, at: usize) -> &AtomicU64 {
        &self.memory.words()[at]
    }

    fn slot_word(&self, slot: usize, field: usize) -> &AtomicU64 {
        self.word(self.layout.slot_at(slot) + field)
    }

    pub(crate) fn incarnation(&self) -> u64 {
        self.word(H_INCARNATION).load(Ordering::Acquire)
    }

    fn database_word(&self, database: usize, field: usize) -> Option<&AtomicU64> {
        (database < self.layout.databases)
            .then(|| self.word(self.layout.database_at(database) + field))
    }

    fn namespace_word(&self, namespace: usize) -> Option<&AtomicU64> {
        (namespace < self.layout.namespaces).then(|| self.word(self.layout.namespace_at(namespace)))
    }

    pub(crate) fn set_available(&self, database: usize, available: bool) -> bool {
        self.database_word(database, D_AVAILABLE)
            .map(|word| word.store(u64::from(available), Ordering::Release))
            .is_some()
    }

    pub(crate) fn set_progress(&self, database: usize, monotonic_ns: u64) -> bool {
        self.database_word(database, D_PROGRESS_NS)
            .map(|word| word.store(monotonic_ns, Ordering::Release))
            .is_some()
    }

    pub(crate) fn set_epoch(&self, namespace: usize, epoch: u64) -> bool {
        self.namespace_word(namespace)
            .map(|word| word.store(epoch, Ordering::Release))
            .is_some()
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
        let epoch = self.namespace_word(query.namespace).ok_or(Miss::Range)?;
        if epoch.load(Ordering::Acquire) != query.epoch {
            return Err(Miss::Epoch);
        }
        Ok(())
    }

    fn key_matches(&self, at: usize, query: &Query<'_>) -> bool {
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
        let Some(stored) = self
            .memory
            .words()
            .get(at..at + length.div_ceil(WORD_BYTES))
        else {
            return false;
        };
        stored
            .iter()
            .zip(expected.chunks(WORD_BYTES))
            .all(|(word, chunk)| word.load(Ordering::Relaxed) == word_of(chunk))
    }

    fn locate(&self, query: &Query<'_>) -> Result<Located, Miss> {
        let hash = hash::key(query.namespace as u64, query.identity, query.shape);
        let key_len = query.key_len();
        let key_words = key_len.div_ceil(WORD_BYTES);
        let arena_start = self.layout.arena_start();
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
            match state & STATE_MASK {
                EMPTY => break,
                OCCUPIED => {}
                _ => continue,
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
            let payload_len = (lengths >> PAYLOAD_SHIFT) as usize;
            let offset = self.slot_word(slot, S_OFFSET).load(Ordering::Relaxed);
            let in_arena = to_usize(offset)
                .and_then(|offset| offset.checked_add(key_words))
                .and_then(|end| end.checked_add(payload_len.div_ceil(WORD_BYTES)))
                .is_some_and(|end| end <= self.layout.arena_words);
            if !in_arena {
                contended = true;
                continue;
            }
            let key_at = arena_start + offset as usize;
            if !self.key_matches(key_at, query) {
                continue;
            }
            if self.slot_word(slot, S_EPOCH).load(Ordering::Relaxed) != query.epoch {
                return Err(Miss::Absent);
            }
            return Ok(Located {
                slot,
                version,
                payload_at: key_at + key_words,
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
        let words = located.payload_len.div_ceil(WORD_BYTES);
        let Some(source) = self
            .memory
            .words()
            .get(located.payload_at..located.payload_at + words)
        else {
            return false;
        };
        for (chunk, word) in destination.chunks_mut(WORD_BYTES).zip(source) {
            let bytes = word.load(Ordering::Relaxed).to_ne_bytes();
            chunk.copy_from_slice(&bytes[..chunk.len()]);
        }
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
}

pub(crate) struct Writer<M> {
    index: Index<M>,
    cursor: usize,
}

impl<M: Words> Writer<M> {
    pub(crate) fn new(index: Index<M>) -> Self {
        Self { index, cursor: 0 }
    }

    fn store_bytes(&self, at: usize, bytes: &[u8]) {
        for (offset, chunk) in bytes.chunks(WORD_BYTES).enumerate() {
            self.index
                .word(at + offset)
                .store(word_of(chunk), Ordering::Relaxed);
        }
    }

    fn find_slot(&self, hash: u64, query: &Query<'_>) -> Option<usize> {
        let index = &self.index;
        let mask = index.layout.slots - 1;
        let mut reusable = None;
        for probe in 0..index.layout.slots {
            let slot = (hash as usize).wrapping_add(probe) & mask;
            let state = index.slot_word(slot, S_STATE).load(Ordering::Relaxed);
            match state & STATE_MASK {
                EMPTY => return reusable.or(Some(slot)),
                OCCUPIED => {
                    let lengths = index.slot_word(slot, S_LENGTHS).load(Ordering::Relaxed);
                    let offset = index.slot_word(slot, S_OFFSET).load(Ordering::Relaxed) as usize;
                    if index.slot_word(slot, S_HASH).load(Ordering::Relaxed) == hash
                        && (state >> NAMESPACE_SHIFT) == query.namespace as u64
                        && (lengths & LENGTH_MASK) == query.key_len() as u64
                        && index.key_matches(index.layout.arena_start() + offset, query)
                    {
                        return Some(slot);
                    }
                }
                _ => {
                    reusable.get_or_insert(slot);
                }
            }
        }
        reusable
    }

    pub(crate) fn publish(
        &mut self,
        query: &Query<'_>,
        payload: &[u8],
        token: u64,
    ) -> Result<usize, Full> {
        let key_len = query.key_len();
        if key_len as u64 > LENGTH_MASK
            || payload.len() as u64 > LENGTH_MASK
            || query.namespace >= self.index.layout.namespaces
        {
            return Err(Full::Entry);
        }
        let key_words = key_len.div_ceil(WORD_BYTES);
        let needed = key_words + payload.len().div_ceil(WORD_BYTES);
        if self.cursor + needed > self.index.layout.arena_words {
            return Err(Full::Arena);
        }
        let hash = hash::key(query.namespace as u64, query.identity, query.shape);
        let slot = self.find_slot(hash, query).ok_or(Full::Slots)?;
        let offset = self.cursor;
        let key_at = self.index.layout.arena_start() + offset;
        let mut key = Vec::with_capacity(key_len);
        key.extend_from_slice(query.identity);
        key.extend_from_slice(query.shape);
        self.store_bytes(key_at, &key);
        self.store_bytes(key_at + key_words, payload);
        self.cursor += needed;
        let index = &self.index;
        let version = index.slot_word(slot, S_VERSION);
        let previous = version.load(Ordering::Relaxed);
        version.store(previous + 1, Ordering::Relaxed);
        fence(Ordering::Release);
        for (field, value) in [
            (S_HASH, hash),
            (
                S_STATE,
                OCCUPIED | ((query.namespace as u64) << NAMESPACE_SHIFT),
            ),
            (S_EPOCH, query.epoch),
            (S_OFFSET, offset as u64),
            (
                S_LENGTHS,
                key_len as u64 | ((payload.len() as u64) << PAYLOAD_SHIFT),
            ),
            (S_TOKEN, token),
        ] {
            index.slot_word(slot, field).store(value, Ordering::Relaxed);
        }
        version.store(previous + 2, Ordering::Release);
        Ok(slot)
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use super::*;
    use crate::memory::zeroed;

    const INCARNATION: u64 = 41;
    const EXPIRY_NS: u64 = 3_000_000_000;
    const NOW_NS: u64 = 10_000_000_000;
    const EPOCH: u64 = 7;

    type Memory = Arc<[AtomicU64]>;

    fn fixture() -> (Index<Memory>, Writer<Memory>) {
        sized_fixture(64)
    }

    fn sized_fixture(arena_words: usize) -> (Index<Memory>, Writer<Memory>) {
        let layout = Layout::new(8, arena_words, 2, 2).unwrap();
        let index = Index::create(zeroed(layout.words()), layout, INCARNATION, EXPIRY_NS).unwrap();
        assert!(index.set_available(0, true));
        assert!(index.set_progress(0, NOW_NS));
        assert!(index.set_epoch(1, EPOCH));
        let writer = Writer::new(index.clone());
        (index, writer)
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

    #[test]
    fn reads_a_published_entry() {
        let (index, mut writer) = fixture();
        writer
            .publish(&query(b"identity"), b"payload bytes", 3)
            .unwrap();
        assert_eq!(
            read(&index, &query(b"identity")),
            Ok((b"payload bytes".to_vec(), 3))
        );
        assert_eq!(read(&index, &query(b"other")), Err(Miss::Absent));
    }

    #[test]
    fn republishing_a_key_replaces_its_entry() {
        let (index, mut writer) = fixture();
        let first = writer.publish(&query(b"identity"), b"first", 1).unwrap();
        let second = writer.publish(&query(b"identity"), b"second", 2).unwrap();
        assert_eq!(first, second);
        assert_eq!(
            read(&index, &query(b"identity")),
            Ok((b"second".to_vec(), 2))
        );
    }

    #[test]
    fn rejects_reads_that_fail_a_validity_check() {
        let (index, mut writer) = fixture();
        writer.publish(&query(b"identity"), b"payload", 1).unwrap();
        let cases: [(&dyn Fn(), u64, Query<'_>, Miss); 6] = [
            (
                &|| {},
                INCARNATION + 1,
                query(b"identity"),
                Miss::Incarnation,
            ),
            (
                &|| {},
                INCARNATION,
                Query {
                    database: 2,
                    ..query(b"identity")
                },
                Miss::Range,
            ),
            (
                &|| {},
                INCARNATION,
                Query {
                    namespace: 2,
                    ..query(b"identity")
                },
                Miss::Range,
            ),
            (
                &|| {},
                INCARNATION,
                Query {
                    database: 1,
                    ..query(b"identity")
                },
                Miss::Unavailable,
            ),
            (
                &|| {},
                INCARNATION,
                Query {
                    epoch: EPOCH + 1,
                    ..query(b"identity")
                },
                Miss::Epoch,
            ),
            (
                &|| assert!(index.set_progress(0, NOW_NS - EXPIRY_NS - 1)),
                INCARNATION,
                query(b"identity"),
                Miss::Expired,
            ),
        ];
        for (prepare, incarnation, query, expected) in cases {
            prepare();
            let outcome = index.read(incarnation, &query, NOW_NS, |_| Some(()));
            assert_eq!(outcome.map(|_| ()), Err(expected));
        }
    }

    #[test]
    fn treats_entries_from_an_older_epoch_as_absent() {
        let (index, mut writer) = fixture();
        writer.publish(&query(b"identity"), b"payload", 1).unwrap();
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
        let slot = writer.publish(&query(b"identity"), b"payload", 1).unwrap();
        for (field, value) in [
            (S_OFFSET, index.layout.arena_words as u64),
            (S_OFFSET, u64::MAX),
            (S_LENGTHS, 16 | (u64::from(u32::MAX) << PAYLOAD_SHIFT)),
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
        writer.publish(&query(b"identity"), b"payload", 1).unwrap();
        let located = index.locate(&query(b"identity")).unwrap();
        assert!(!index.copy_payload(&located, &mut [0; 3]));
    }

    #[test]
    fn a_write_between_locate_and_validate_rejects_the_copy() {
        let (index, mut writer) = fixture();
        writer.publish(&query(b"identity"), b"first", 1).unwrap();
        let located = index.locate(&query(b"identity")).unwrap();
        writer.publish(&query(b"identity"), b"other", 2).unwrap();
        assert!(!index.validate(&located));
    }

    #[test]
    fn a_slot_left_mid_write_is_contended() {
        let (index, mut writer) = fixture();
        let slot = writer.publish(&query(b"identity"), b"payload", 1).unwrap();
        index
            .slot_word(slot, S_VERSION)
            .fetch_add(1, Ordering::Relaxed);
        assert_eq!(read(&index, &query(b"identity")), Err(Miss::Contended));
    }

    #[test]
    fn concurrent_rewrites_never_yield_mixed_payloads() {
        const ROUNDS: u64 = 20_000;
        let (index, mut writer) = sized_fixture(8 * ROUNDS as usize);
        let payloads = [vec![b'a'; 40], vec![b'b'; 40]];
        let observed = std::thread::scope(|scope| {
            let handle = scope.spawn(|| {
                (0..ROUNDS)
                    .filter_map(|_| read(&index, &query(b"identity")).ok())
                    .collect::<Vec<_>>()
            });
            for round in 0..ROUNDS {
                writer
                    .publish(&query(b"identity"), &payloads[(round % 2) as usize], round)
                    .unwrap();
            }
            handle.join().unwrap()
        });
        assert!(
            observed
                .iter()
                .all(|(payload, token)| *payload == payloads[(token % 2) as usize])
        );
    }

    #[test]
    fn exhausted_capacity_is_reported() {
        let (_index, mut writer) = fixture();
        assert_eq!(
            writer.publish(&query(b"big"), &[0; 1024], 1),
            Err(Full::Arena)
        );
        for identity in 0..8_u8 {
            writer.publish(&query(&[identity]), b"x", 1).unwrap();
        }
        assert_eq!(writer.publish(&query(b"ninth"), b"x", 1), Err(Full::Slots));
    }
}
