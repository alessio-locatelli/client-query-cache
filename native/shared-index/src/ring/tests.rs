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
    assert!(Ring::<std::sync::Arc<[AtomicU64]>>::words_for(0).is_none());
    assert!(Ring::create(zeroed(HEADER_WORDS + 1), 2).is_none());
    assert!(Ring::create(zeroed(HEADER_WORDS), 0).is_none());
}
