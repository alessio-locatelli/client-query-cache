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

#[test]
fn producer_rejects_a_consumer_position_ahead_of_publication() {
    let queue = frames(32);
    queue.word(HEAD).store(1, Ordering::Relaxed);
    assert!(!queue.push(b"frame"));
}
