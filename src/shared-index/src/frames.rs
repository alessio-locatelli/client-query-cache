use crate::memory::{WORD_BYTES, Words};
use crate::sync::{AtomicU64, Ordering};

const HEAD: usize = 0;
const TAIL: usize = 1;
const CAPACITY: usize = 2;
const HEADER_WORDS: usize = 3;

// One producer and one consumer; Python bindings serialize callers on each side.
// Record bodies are atomic words so even a damaged peer cannot cause a data race.
pub(crate) struct Frames<M> {
    memory: M,
    start: usize,
    capacity: usize,
}

impl<M: Words> Frames<M> {
    pub(crate) fn words_for(bytes: usize) -> Option<usize> {
        let capacity = bytes / WORD_BYTES;
        (capacity >= 2).then_some(capacity.checked_add(HEADER_WORDS)?)
    }

    pub(crate) fn create(memory: M, start: usize, bytes: usize) -> Option<Self> {
        if memory.words().len() < start.checked_add(Self::words_for(bytes)?)? {
            return None;
        }
        let capacity = bytes / WORD_BYTES;
        memory.words()[start + CAPACITY].store(capacity as u64, Ordering::Release);
        Some(Self {
            memory,
            start,
            capacity,
        })
    }

    pub(crate) fn attach(memory: M, start: usize) -> Option<Self> {
        let capacity = usize::try_from(
            memory
                .words()
                .get(start.checked_add(CAPACITY)?)?
                .load(Ordering::Acquire),
        )
        .ok()?;
        if capacity < 2
            || memory.words().len() != start.checked_add(HEADER_WORDS)?.checked_add(capacity)?
        {
            return None;
        }
        Some(Self {
            memory,
            start,
            capacity,
        })
    }

    fn word(&self, index: usize) -> &AtomicU64 {
        &self.memory.words()[self.start + index]
    }

    fn body(&self, position: u64) -> &AtomicU64 {
        self.word(HEADER_WORDS + (position % self.capacity as u64) as usize)
    }

    pub(crate) fn push(&self, frame: &[u8]) -> bool {
        if frame.is_empty() {
            return false;
        }
        let needed = 1 + frame.len().div_ceil(WORD_BYTES) as u64;
        let tail = self.word(TAIL).load(Ordering::Relaxed);
        let head = self.word(HEAD).load(Ordering::Acquire);
        let Some(pending) = tail.checked_sub(head) else {
            return false;
        };
        let Some(end) = tail.checked_add(needed) else {
            return false;
        };
        if needed > self.capacity as u64 || pending > self.capacity as u64 - needed {
            return false;
        }
        self.body(tail).store(frame.len() as u64, Ordering::Relaxed);
        for (offset, chunk) in frame.chunks(WORD_BYTES).enumerate() {
            let mut bytes = [0; WORD_BYTES];
            bytes[..chunk.len()].copy_from_slice(chunk);
            self.body(tail + 1 + offset as u64)
                .store(u64::from_le_bytes(bytes), Ordering::Relaxed);
        }
        // A producer killed before this store leaves no visible partial record.
        self.word(TAIL).store(end, Ordering::Release);
        true
    }

    pub(crate) fn drain(&self, limit: usize) -> Result<Vec<Vec<u8>>, ()> {
        let tail = self.word(TAIL).load(Ordering::Acquire);
        let mut head = self.word(HEAD).load(Ordering::Relaxed);
        let pending = tail.checked_sub(head).ok_or(())?;
        if pending > self.capacity as u64 {
            return Err(());
        }
        let mut frames = Vec::new();
        while head < tail && frames.len() < limit {
            let length =
                usize::try_from(self.body(head).load(Ordering::Relaxed)).map_err(|_| ())?;
            let needed = 1 + length.div_ceil(WORD_BYTES) as u64;
            if length == 0 || needed > tail - head {
                return Err(());
            }
            let mut frame = vec![0; length];
            for (offset, chunk) in frame.chunks_mut(WORD_BYTES).enumerate() {
                let bytes = self
                    .body(head + 1 + offset as u64)
                    .load(Ordering::Relaxed)
                    .to_le_bytes();
                chunk.copy_from_slice(&bytes[..chunk.len()]);
            }
            frames.push(frame);
            head += needed;
            // Reuse is allowed only after the complete record has been copied.
            self.word(HEAD).store(head, Ordering::Release);
        }
        Ok(frames)
    }
}

#[cfg(all(test, not(loom)))]
mod tests;

#[cfg(all(test, loom))]
mod models {
    use super::*;
    use crate::memory::zeroed;

    #[test]
    fn publication_and_reuse_never_expose_partial_frames() {
        loom::model(|| {
            let queue =
                std::sync::Arc::new(Frames::create(zeroed(HEADER_WORDS + 2), 0, 16).unwrap());
            let producer = queue.clone();
            let writer = loom::thread::spawn(move || {
                assert!(producer.push(b"first"));
                // The second record can be dropped when the consumer has not freed space.
                producer.push(b"second")
            });
            let first = queue.drain(usize::MAX).unwrap();
            let second_published = writer.join().unwrap();
            let remaining = queue.drain(usize::MAX).unwrap();
            let observed: Vec<_> = first.into_iter().chain(remaining).collect();
            assert_eq!(
                observed,
                if second_published {
                    vec![b"first".to_vec(), b"second".to_vec()]
                } else {
                    vec![b"first".to_vec()]
                }
            );
        });
    }
}
