use crate::memory::Words;
use crate::sync::{AtomicU64, Ordering};

const R_HEAD: usize = 0;
const R_TAIL: usize = 1;
const R_CAPACITY: usize = 2;
const R_DROPPED: usize = 3;
const HEADER_WORDS: usize = 4;

#[derive(Clone)]
pub(crate) struct Ring<M> {
    memory: M,
    capacity: usize,
}

impl<M: Words> Ring<M> {
    pub(crate) fn words_for(capacity: usize) -> Option<usize> {
        capacity.checked_add(HEADER_WORDS)
    }

    pub(crate) fn create(memory: M, capacity: usize) -> Option<Self> {
        if capacity == 0 || memory.words().len() < Self::words_for(capacity)? {
            return None;
        }
        memory.words()[R_CAPACITY].store(capacity as u64, Ordering::Release);
        Some(Self { memory, capacity })
    }

    pub(crate) fn attach(memory: M) -> Option<Self> {
        let words = memory.words();
        let capacity = usize::try_from(words.get(R_CAPACITY)?.load(Ordering::Acquire)).ok()?;
        if capacity == 0 || words.len() < Self::words_for(capacity)? {
            return None;
        }
        Some(Self { memory, capacity })
    }

    fn word(&self, at: usize) -> &AtomicU64 {
        &self.memory.words()[at]
    }

    fn token(&self, position: u64) -> &AtomicU64 {
        self.word(HEADER_WORDS + (position % self.capacity as u64) as usize)
    }

    pub(crate) fn push(&self, token: u64) -> bool {
        let tail = self.word(R_TAIL).load(Ordering::Relaxed);
        let head = self.word(R_HEAD).load(Ordering::Acquire);
        if tail.wrapping_sub(head) >= self.capacity as u64 {
            self.word(R_DROPPED).fetch_add(1, Ordering::Relaxed);
            return false;
        }
        self.token(tail).store(token, Ordering::Relaxed);
        self.word(R_TAIL)
            .store(tail.wrapping_add(1), Ordering::Release);
        true
    }

    pub(crate) fn drain(&self, mut visit: impl FnMut(u64)) -> usize {
        let tail = self.word(R_TAIL).load(Ordering::Acquire);
        let head = self.word(R_HEAD).load(Ordering::Relaxed);
        let pending = tail.wrapping_sub(head).min(self.capacity as u64);
        for offset in 0..pending {
            visit(
                self.token(head.wrapping_add(offset))
                    .load(Ordering::Relaxed),
            );
        }
        self.word(R_HEAD)
            .store(head.wrapping_add(pending), Ordering::Release);
        pending as usize
    }

    pub(crate) fn dropped(&self) -> u64 {
        self.word(R_DROPPED).load(Ordering::Relaxed)
    }
}

#[cfg(all(test, not(loom)))]
mod tests {
    use super::*;
    use crate::memory::zeroed;

    fn ring(capacity: usize) -> Ring<std::sync::Arc<[AtomicU64]>> {
        Ring::create(
            zeroed(Ring::<std::sync::Arc<[AtomicU64]>>::words_for(capacity).unwrap()),
            capacity,
        )
        .unwrap()
    }

    fn drained(ring: &Ring<std::sync::Arc<[AtomicU64]>>) -> Vec<u64> {
        let mut tokens = Vec::new();
        ring.drain(|token| tokens.push(token));
        tokens
    }

    #[test]
    fn drains_tokens_in_push_order_across_wraparound() {
        let ring = ring(3);
        assert!(ring.push(1) && ring.push(2));
        assert_eq!(drained(&ring), [1, 2]);
        assert!(ring.push(3) && ring.push(4) && ring.push(5));
        assert_eq!(drained(&ring), [3, 4, 5]);
    }

    #[test]
    fn a_full_ring_drops_tokens_instead_of_blocking() {
        let ring = ring(2);
        assert!(ring.push(1) && ring.push(2));
        assert!(!ring.push(3));
        assert_eq!(ring.dropped(), 1);
        assert_eq!(drained(&ring), [1, 2]);
    }

    #[test]
    fn a_corrupted_tail_drains_at_most_one_capacity() {
        let ring = ring(2);
        ring.word(R_TAIL).store(u64::MAX / 2, Ordering::Relaxed);
        assert_eq!(drained(&ring).len(), 2);
    }

    #[test]
    fn attaches_to_a_created_ring() {
        let created = ring(2);
        let attached = Ring::attach(created.memory.clone()).unwrap();
        assert!(attached.push(7));
        assert_eq!(drained(&created), [7]);
        assert!(Ring::attach(zeroed(HEADER_WORDS)).is_none());
        let truncated = zeroed(HEADER_WORDS + 1);
        truncated[R_CAPACITY].store(2, Ordering::Relaxed);
        assert!(Ring::attach(truncated).is_none());
    }

    #[test]
    fn rejects_undersized_memory() {
        assert!(Ring::create(zeroed(HEADER_WORDS + 1), 2).is_none());
        assert!(Ring::create(zeroed(HEADER_WORDS), 0).is_none());
    }
}
