use super::*;

fn find_identity(limit: u64) -> [u8; 16] {
    let mut identity = *b"\0\0\0\0find\0\0\0\0\0\0\0\0";
    identity[8..].copy_from_slice(&limit.to_le_bytes());
    identity
}

fn family_hash(query: &Query<'_>) -> NonZeroU64 {
    let hash = hash::key(
        query.namespace as u64,
        &query.epoch.to_le_bytes(),
        query.shape,
    );
    NonZeroU64::new(hash).unwrap_or(NonZeroU64::MAX)
}

impl<M: Words> Index<M> {
    pub(crate) fn set_find_complete(&self, namespace: usize, complete: bool) -> bool {
        let Some(word) = self.namespace_word(namespace, N_FIND_COMPLETE) else {
            return false;
        };
        word.store(u64::from(!complete), Ordering::Release);
        true
    }

    pub(crate) fn find_complete(&self, namespace: usize) -> bool {
        self.namespace_word(namespace, N_FIND_COMPLETE)
            .is_some_and(|word| word.load(Ordering::Acquire) == 0)
    }

    fn filter_cells(&self, hash: NonZeroU64) -> [usize; 2] {
        let mask = self.layout.slots - 1;
        [
            hash.get() as usize & mask,
            hash.get().rotate_left(32) as usize & mask,
        ]
    }

    fn filter_word(&self, cell: usize) -> &AtomicU64 {
        self.word(self.layout.filter_start() + cell)
    }

    pub(crate) fn read_find<T>(
        &self,
        incarnation: u64,
        family: &Query<'_>,
        limit: u64,
        now_ns: u64,
        copy: impl FnMut(&Located) -> Option<T>,
    ) -> Result<(T, u64), Miss> {
        self.check(incarnation, family, now_ns)?;
        let family_hash = family_hash(family);
        let identity = find_identity(limit);
        let exact = Query {
            identity: &identity,
            ..*family
        };
        let outcome = self.read_hashed(&exact, hash::find_limit(family_hash.get(), limit), copy);
        if matches!(outcome, Err(Miss::Absent)) {
            let [first, second] = self.filter_cells(family_hash);
            if self.filter_word(first).load(Ordering::Acquire) != 0
                && (first == second || self.filter_word(second).load(Ordering::Acquire) != 0)
            {
                return Err(Miss::PossibleFamily);
            }
        }
        outcome
    }
}

impl<M: Words> Writer<M> {
    pub(super) fn update_filter(&self, hash: NonZeroU64, insert: bool) {
        let [first, second] = self.index.filter_cells(hash);
        for cell in [Some(first), (second != first).then_some(second)]
            .into_iter()
            .flatten()
        {
            let word = self.index.filter_word(cell);
            if insert {
                word.fetch_add(1, Ordering::Release);
            } else {
                word.fetch_sub(1, Ordering::Release);
            }
        }
    }

    pub(super) fn remove_find(&mut self, slot: &Slot) {
        let allocation = self
            .index
            .arena(slot.payload_at as usize - BLOCK_HEADER_WORDS)
            .load(Ordering::Relaxed) as usize;
        if let Some(hash) = self.allocations[allocation].take_find_hash() {
            self.update_filter(hash, false);
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
        self.publish_hashed(&exact, payload, || {
            let family_hash = family_hash(query);
            (
                hash::find_limit(family_hash.get(), limit),
                Some(family_hash),
            )
        })
    }
}
