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
        if capacity == 0 {
            return None;
        }
        capacity.checked_add(HEADER_WORDS)
    }

    pub(crate) fn create(memory: M, capacity: usize) -> Option<Self> {
        if memory.words().len() < Self::words_for(capacity)? {
            return None;
        }
        memory.words()[R_CAPACITY].store(capacity as u64, Ordering::Release);
        Some(Self { memory, capacity })
    }

    pub(crate) fn attach(memory: M) -> Option<Self> {
        let words = memory.words();
        let capacity = usize::try_from(words.get(R_CAPACITY)?.load(Ordering::Acquire)).ok()?;
        if words.len() < Self::words_for(capacity)? {
            return None;
        }
        Some(Self { memory, capacity })
    }

    fn word(&self, at: usize) -> &AtomicU64 {
        &self.memory.words()[at]
    }

    pub(crate) fn words(&self) -> usize {
        HEADER_WORDS + self.capacity
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
mod tests;
