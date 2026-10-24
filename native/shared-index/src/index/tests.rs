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
fn stored_fragments_preserve_word_boundaries_and_reuse() {
    let (index, mut writer) = fixture();
    for first_length in 0..=WORD_BYTES * 2 + 1 {
        for second_length in 0..=WORD_BYTES * 2 + 1 {
            let first = vec![0x11; first_length];
            let second = vec![0x22; second_length];
            let third = [0x33; 3];
            let expected = [first.as_slice(), second.as_slice(), &third].concat();
            let block = writer.allocate(expected.len()).unwrap();
            writer.write_bytes(
                block.at + BLOCK_HEADER_WORDS,
                &[&first, &[], &second, &third],
            );
            assert_eq!(index.snapshot(block), Some(expected));
            writer.release(block);
        }
    }
}

#[test]
fn payloads_cross_word_and_page_boundaries() {
    for length in [7, 8, 9, 4095, 4096, 4097, 65_535, 65_536, 65_537] {
        let (index, mut writer) = sized_fixture(8, block_words(length) + 256);
        let expected = (0..length).map(|offset| offset as u8).collect::<Vec<_>>();
        let block = publish(&mut writer, b"identity", &expected);
        assert_eq!(
            read(&index, &query(b"identity")),
            Ok((expected, block.token()))
        );
        writer.release(block);
    }
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

#[test]
fn rejects_a_descriptor_with_an_invalid_published_layout() {
    let (index, _writer) = fixture();
    index.word(H_SLOTS).store(0, Ordering::Release);
    assert!(Index::attach(index.memory).is_none());
}
