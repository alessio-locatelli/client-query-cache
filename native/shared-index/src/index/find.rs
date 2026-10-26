use std::collections::{BTreeMap, HashMap};
use std::sync::Arc;

use super::*;

const CORE_INCOMPLETE: u64 = 1;
const DIRECTORIES_INCOMPLETE: u64 = 2;
const FAMILY_ID: &[u8] = b"\0\0\0\0family";

fn directory_bytes(entries: usize) -> Option<usize> {
    u32::try_from(entries.checked_mul(WORD_BYTES)?)
        .ok()
        .map(|length| length as usize)
}

fn find_identity(limit: u64) -> [u8; 16] {
    let mut identity = *b"\0\0\0\0find\0\0\0\0\0\0\0\0";
    identity[8..].copy_from_slice(&limit.to_le_bytes());
    identity
}

#[derive(Clone, PartialEq, Eq, Hash)]
struct Family {
    database: usize,
    namespace: usize,
    epoch: u64,
    key: Arc<[u8]>,
}

impl Family {
    fn scope(&self) -> (usize, usize, u64) {
        (self.database, self.namespace, self.epoch)
    }

    fn query(&self) -> Query<'_> {
        Query {
            database: self.database,
            namespace: self.namespace,
            epoch: self.epoch,
            identity: FAMILY_ID,
            shape: &self.key,
        }
    }
}

#[derive(Default)]
struct Members {
    entries: BTreeMap<u64, Block>,
    directory: Option<Block>,
}

impl Members {
    fn limits(&self) -> impl Iterator<Item = u64> + '_ {
        self.entries
            .keys()
            .copied()
            .filter(|limit| *limit != 0)
            .chain(self.entries.contains_key(&0).then_some(0))
    }
}

type FamilyMembers = HashMap<Arc<[u8]>, Members>;

pub(super) struct FindPublications {
    entries: HashMap<u64, (Family, u64)>,
    families: HashMap<(usize, usize, u64), FamilyMembers>,
    failures: HashMap<usize, usize>,
    pub(super) directories: usize,
}

impl FindPublications {
    pub(super) fn new() -> Self {
        Self {
            entries: HashMap::new(),
            families: HashMap::new(),
            failures: HashMap::new(),
            directories: 0,
        }
    }
}

impl<M: Words> Index<M> {
    fn find_flag(&self, namespace: usize, flag: u64, complete: bool) -> bool {
        let Some(word) = self.namespace_word(namespace, N_FIND_COMPLETE) else {
            return false;
        };
        if complete {
            word.fetch_and(!flag, Ordering::Release);
        } else {
            word.fetch_or(flag, Ordering::Release);
        }
        true
    }

    pub(crate) fn set_find_complete(&self, namespace: usize, complete: bool) -> bool {
        self.find_flag(namespace, CORE_INCOMPLETE, complete)
    }

    pub(crate) fn find_complete(&self, namespace: usize) -> bool {
        self.namespace_word(namespace, N_FIND_COMPLETE)
            .is_some_and(|word| word.load(Ordering::Acquire) == 0)
    }

    pub(crate) fn read_find<T>(
        &self,
        incarnation: u64,
        family: &Query<'_>,
        limit: u64,
        now_ns: u64,
        mut copy: impl FnMut(&Located) -> Option<T>,
    ) -> Result<(T, u64), Miss> {
        let identity = find_identity(limit);
        let exact = Query {
            identity: &identity,
            ..*family
        };
        match self.read(incarnation, &exact, now_ns, &mut copy) {
            Err(Miss::Absent) if limit != 0 => {}
            outcome => return outcome,
        }
        let directory = Query {
            identity: FAMILY_ID,
            ..*family
        };
        let (limits, _) = self.read(incarnation, &directory, now_ns, |located| {
            let mut bytes = vec![0; located.payload_len];
            self.copy_payload(located, &mut bytes).then_some(bytes)
        })?;
        let count = limits.len() / WORD_BYTES;
        let at = |offset: usize| {
            u64::from_le_bytes(
                limits[offset * WORD_BYTES..(offset + 1) * WORD_BYTES]
                    .try_into()
                    .unwrap(),
            )
        };
        let mut low = 0;
        let mut high = count;
        while low < high {
            let middle = low + (high - low) / 2;
            let candidate = at(middle);
            if candidate != 0 && candidate < limit {
                low = middle + 1;
            } else {
                high = middle;
            }
        }
        for offset in low..count {
            let identity = find_identity(at(offset));
            let query = Query {
                identity: &identity,
                ..*family
            };
            match self.read(incarnation, &query, now_ns, &mut copy) {
                Err(Miss::Absent) => {}
                outcome => return outcome,
            }
        }
        Err(Miss::Absent)
    }
}

impl<M: Words> Writer<M> {
    fn find_failure(&mut self, namespace: usize, failed: bool) {
        if failed {
            *self.finds.failures.entry(namespace).or_default() += 1;
        } else {
            let failures = self.finds.failures.get_mut(&namespace).unwrap();
            *failures -= 1;
            if *failures == 0 {
                self.finds.failures.remove(&namespace);
            }
        }
        self.index.find_flag(
            namespace,
            DIRECTORIES_INCOMPLETE,
            !self.finds.failures.contains_key(&namespace),
        );
    }

    fn rebuild_family(&mut self, family: &Family, members: &mut Members) {
        let byte_length = directory_bytes(members.entries.len());
        if let (Some(directory), Some(length)) = (members.directory, byte_length) {
            let capacity = (self.allocations[directory.allocation].words as usize
                - BLOCK_HEADER_WORDS)
                * WORD_BYTES;
            if capacity >= length && capacity < length.saturating_mul(4) {
                let slot = self.published[&directory.token()];
                let mut fields = self.read_slot(slot);
                fields.lengths = (fields.lengths & LENGTH_MASK) | ((length as u64) << HIGH_SHIFT);
                self.allocations[directory.allocation].length = length as u32;
                self.write_slot_with(slot, &fields, || self.write_limits(directory, members));
                return;
            }
        }
        if let Some(directory) = members.directory.take() {
            self.find_failure(family.namespace, true);
            self.finds.directories -= 1;
            self.release(directory);
        }
        if let Some((directory, length)) = byte_length.and_then(|length| {
            self.allocate(length.next_power_of_two())
                .map(|directory| (directory, length))
        }) {
            self.allocations[directory.allocation].length = length as u32;
            self.write_limits(directory, members);
            if self.publish(&family.query(), directory).is_ok() {
                members.directory = Some(directory);
                self.finds.directories += 1;
                self.find_failure(family.namespace, false);
            } else {
                self.release(directory);
            }
        }
    }

    fn write_limits(&self, directory: Block, members: &Members) {
        for (offset, limit) in members.limits().enumerate() {
            self.index
                .arena(directory.at + BLOCK_HEADER_WORDS + offset)
                .store(limit, Ordering::Relaxed);
        }
    }

    pub(crate) fn publish_find(
        &mut self,
        query: &Query<'_>,
        limit: u64,
        payload: Block,
    ) -> Result<u64, Refusal> {
        let identity = find_identity(limit);
        let exact = Query {
            identity: &identity,
            ..*query
        };
        let token = self.publish(&exact, payload)?;
        if self.finds.entries.contains_key(&token) {
            return Ok(token);
        }
        let scope = (query.database, query.namespace, query.epoch);
        let mut families = self.finds.families.remove(&scope).unwrap_or_default();
        let (key, mut members) = match families.remove_entry(query.shape) {
            Some(pair) => pair,
            None => {
                self.find_failure(query.namespace, true);
                (Arc::from(query.shape), Members::default())
            }
        };
        let family = Family {
            database: query.database,
            namespace: query.namespace,
            epoch: query.epoch,
            key: key.clone(),
        };
        if let Some(previous) = members.entries.insert(limit, payload) {
            self.finds.entries.remove(&previous.token());
        }
        self.finds.entries.insert(token, (family.clone(), limit));
        self.rebuild_family(&family, &mut members);
        families.insert(key, members);
        self.finds.families.insert(scope, families);
        Ok(token)
    }

    pub(super) fn unpublish_find(&mut self, payload: Block) -> Option<bool> {
        let (family, limit) = self.finds.entries.remove(&payload.token())?;
        let removed = self.unpublish_live(payload);
        let scope = family.scope();
        let mut families = self.finds.families.remove(&scope).unwrap();
        let mut members = families.remove(family.key.as_ref()).unwrap();
        members.entries.remove(&limit);
        if members.entries.is_empty() {
            if let Some(directory) = members.directory {
                self.finds.directories -= 1;
                self.release(directory);
            } else {
                self.find_failure(family.namespace, false);
            }
        } else {
            self.rebuild_family(&family, &mut members);
            families.insert(family.key, members);
        }
        if !families.is_empty() {
            self.finds.families.insert(scope, families);
        }
        Some(removed)
    }
}

#[cfg(all(test, not(loom)))]
mod tests {
    use super::*;

    #[test]
    fn directory_lengths_fit_the_encoded_payload_field() {
        let maximum = u32::MAX as usize / WORD_BYTES;
        assert_eq!(directory_bytes(1), Some(WORD_BYTES));
        assert_eq!(directory_bytes(maximum), Some(maximum * WORD_BYTES));
        assert_eq!(directory_bytes(maximum + 1), None);
        assert_eq!(directory_bytes(usize::MAX), None);
    }
}
