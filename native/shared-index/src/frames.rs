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
mod tests {
    use super::*;
    use crate::memory::zeroed;

    fn frames(bytes: usize) -> Frames<std::sync::Arc<[AtomicU64]>> {
        Frames::create(
            zeroed(Frames::<std::sync::Arc<[AtomicU64]>>::words_for(bytes).unwrap()),
            0,
            bytes,
        )
        .unwrap()
    }

    #[test]
    fn records_wrap_without_padding_or_reordering() {
        let queue = frames(40);
        for payload in [
            b"abcdefghijk".as_slice(),
            b"x",
            b"longer than one word",
            b"yz",
        ] {
            assert!(queue.push(payload));
            assert_eq!(queue.drain(usize::MAX).unwrap(), [payload]);
        }
    }

    #[test]
    fn a_full_queue_falls_back_without_overwriting_records() {
        let queue = frames(32);
        assert!(queue.push(b"one") && queue.push(b"two"));
        assert!(!queue.push(b"three"));
        assert_eq!(queue.drain(usize::MAX).unwrap(), [b"one", b"two"]);
        assert!(queue.push(b"three"));
        assert!(!queue.push(b""));
        assert!(!queue.push(&[0; 32]));
    }

    #[test]
    fn attaches_after_an_existing_ring_and_rejects_truncated_memory() {
        let start = 7;
        let memory = zeroed(start + Frames::<std::sync::Arc<[AtomicU64]>>::words_for(32).unwrap());
        let producer = Frames::create(memory.clone(), start, 32).unwrap();
        let consumer = Frames::attach(memory.clone(), start).unwrap();
        assert!(producer.push(b"frame"));
        assert_eq!(consumer.drain(usize::MAX).unwrap(), [b"frame"]);
        assert!(Frames::attach(memory, start + 1).is_none());
        assert!(Frames::create(zeroed(HEADER_WORDS), 0, 16).is_none());
        assert!(Frames::<std::sync::Arc<[AtomicU64]>>::words_for(8).is_none());
    }

    #[test]
    fn damaged_positions_and_lengths_fail_closed() {
        for (head, tail, length) in [
            (1, 0, 1),
            (0, 5, 1),
            (0, 1, 100),
            (0, 1, 0),
            (0, 1, u64::MAX),
        ] {
            let queue = frames(32);
            queue.body(0).store(length, Ordering::Relaxed);
            queue.word(HEAD).store(head, Ordering::Relaxed);
            queue.word(TAIL).store(tail, Ordering::Relaxed);
            assert!(queue.drain(usize::MAX).is_err());
        }
        let queue = frames(32);
        queue.word(HEAD).store(u64::MAX, Ordering::Relaxed);
        queue.word(TAIL).store(u64::MAX, Ordering::Relaxed);
        assert!(!queue.push(b"overflow"));
    }
}

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
