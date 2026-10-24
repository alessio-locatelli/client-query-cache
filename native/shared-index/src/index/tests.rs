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
    let (_index, mut writer) = fixture();
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
            assert_eq!(writer.snapshot_copy(block), Some(expected));
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
    let (_index, mut writer) = fixture();
    let first = writer.store(b"first payload").unwrap();
    assert_eq!(writer.snapshot_copy(first), Some(b"first payload".to_vec()));
    writer.release(first);
    assert_eq!(writer.snapshot_copy(first), None);
    let reused = writer.store(b"other payload").unwrap();
    assert_eq!(reused.at, first.at);
    assert_eq!(writer.snapshot_copy(first), None);
    writer.release(first);
    assert_eq!(
        writer.snapshot_copy(reused),
        Some(b"other payload".to_vec())
    );
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
    let (_index, mut writer) = sized_fixture(8, 4);
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

#[test]
fn rejects_an_undersized_owner_mapping_before_publishing_a_header() {
    let layout = Layout::new(8, 64, 1, 1).unwrap();
    let memory = zeroed(layout.words() - 1);
    assert!(Index::create(memory.clone(), layout, INCARNATION, EXPIRY_NS).is_none());
    assert!(memory.iter().all(|word| word.load(Ordering::Relaxed) == 0));
}

#[test]
fn a_location_from_a_larger_index_cannot_copy_outside_a_smaller_mapping() {
    let (large, mut writer) = sized_fixture(8, 1024);
    writer.store(&[0; 2048]).unwrap();
    publish(&mut writer, b"identity", b"payload");
    let located = large.locate(&query(b"identity")).unwrap();
    let (small, _) = sized_fixture(8, 64);
    let mut destination = [0xa5; 7];
    assert!(!small.copy_payload(&located, &mut destination));
    assert_eq!(destination, [0xa5; 7]);
}

#[test]
fn a_release_after_snapshot_sizing_invalidates_the_copy() {
    let (_index, mut writer) = fixture();
    let block = writer.store(b"payload").unwrap();
    assert!(writer.snapshot(block).is_some());
    writer.release(block);
    assert!(writer.snapshot(block).is_none());
}

#[test]
fn equal_hashes_do_not_replace_or_return_a_different_identity() {
    // Each pair has the same full hash in namespace 1, including unequal-length keys.
    const COLLISIONS: [(&[u8], &[u8]); 2] = [
        (
            &[0; 16],
            &[
                1, 0, 0, 0, 0, 0, 0, 0, 0xae, 0x52, 0x43, 0x1c, 0xe5, 0xca, 0xe9, 0x37,
            ],
        ),
        (
            &[0; 8],
            &[
                0, 0, 0, 0, 0, 0, 0, 0, 0xbf, 0xcc, 0x1e, 0x61, 0x33, 0xe7, 0xf5, 0xc7,
            ],
        ),
    ];
    for (first_identity, second_identity) in COLLISIONS {
        let first = query(first_identity);
        let second = query(second_identity);
        assert_eq!(first.hash(), second.hash());
        assert_ne!(first.identity, second.identity);
        let (index, mut writer) = fixture();
        let first_block = publish(&mut writer, first.identity, b"first");
        let second_block = publish(&mut writer, second.identity, b"second");
        assert_eq!(writer.published(), 2);
        assert_eq!(
            read(&index, &first),
            Ok((b"first".to_vec(), first_block.token()))
        );
        assert_eq!(
            read(&index, &second),
            Ok((b"second".to_vec(), second_block.token()))
        );
        writer.release(first_block);
        assert_eq!(read(&index, &first), Err(Miss::Absent));
        assert_eq!(
            read(&index, &second),
            Ok((b"second".to_vec(), second_block.token()))
        );
    }
}

#[cfg(target_pointer_width = "64")]
#[test]
fn refuses_payloads_larger_than_the_encoded_length_without_reading_them() {
    use crate::memory::Mapping;

    let length = usize::try_from(LENGTH_MASK + 1).unwrap();
    let (mapping, _descriptor) = Mapping::memfd(c"oversized-payload", length / WORD_BYTES).unwrap();
    // The sparse mapping is initialized by the kernel and has no writers.
    let payload =
        unsafe { std::slice::from_raw_parts(mapping.words().as_ptr().cast::<u8>(), length) };
    let (_index, mut writer) = fixture();
    assert_eq!(writer.store(payload), None);
    let resident = writer.store(b"resident").unwrap();
    let oversized_key = Query {
        identity: payload,
        shape: &[],
        ..query(&[])
    };
    assert_eq!(
        writer.publish(&oversized_key, resident),
        Err(Refusal::Entry)
    );
    assert_eq!(writer.published(), 0);
}

#[test]
fn publication_outside_the_namespace_layout_is_refused() {
    let (index, mut writer) = fixture();
    let payload = writer.store(b"payload").unwrap();
    let outside = Query {
        namespace: index.layout.namespaces,
        ..query(b"identity")
    };
    assert_eq!(writer.publish(&outside, payload), Err(Refusal::Entry));
    assert_eq!(writer.published(), 0);
    assert!(writer.is_live(payload));
}

#[test]
fn released_capacity_survives_changing_size_classes() {
    let (_index, mut writer) = sized_fixture(8, 4096 / WORD_BYTES);
    for length in [1000, 900, 800, 700, 400, 200, 3000, 100] {
        let payload = vec![0x42; length];
        let block = writer.store(&payload).expect("released arena capacity");
        assert_eq!(writer.snapshot_copy(block), Some(payload));
        writer.release(block);
    }
}

#[test]
fn adjacent_free_blocks_can_satisfy_a_larger_request() {
    for order in [[0, 1, 2], [0, 2, 1], [2, 0, 1]] {
        let (_index, mut writer) = sized_fixture(8, 64);
        let blocks: Vec<Block> = (0..4)
            .map(|value| writer.store(&[value; 120]).unwrap())
            .collect();
        for offset in order {
            writer.release(blocks[offset]);
        }
        let combined = writer.store(&[4; 368]).expect("adjacent released blocks");
        assert_eq!(writer.snapshot_copy(combined), Some(vec![4; 368]));
        assert_eq!(writer.snapshot_copy(blocks[3]), Some(vec![3; 120]));
    }
}

#[test]
fn merged_payload_bytes_cannot_revive_an_obsolete_block() {
    let (_index, mut writer) = sized_fixture(8, 64);
    let first = writer.store(&[1; 112]).unwrap();
    let second = writer.store(&[2; 112]).unwrap();
    writer.release(first);
    writer.release(second);
    let mut payload = vec![0; 240];
    let offset = (second.at - BLOCK_HEADER_WORDS) * WORD_BYTES;
    payload[offset..offset + WORD_BYTES].copy_from_slice(&second.version.to_ne_bytes());
    let combined = writer.store(&payload).unwrap();
    assert_eq!(writer.snapshot_copy(second), None);
    assert_eq!(
        writer.publish(&query(b"obsolete"), second),
        Err(Refusal::Dead)
    );
    writer.release(second);
    assert_eq!(writer.snapshot_copy(combined), Some(payload));
}

#[test]
fn stale_owner_handles_cannot_unpublish_after_wire_token_wrap() {
    let (index, mut writer) = fixture();
    let first = publish(&mut writer, b"first", b"old");
    writer.release(first);
    writer.next_version = (1_u64 << HIGH_SHIFT) + first.version;
    let replacement = publish(&mut writer, b"replacement", b"new");
    assert_eq!(first.token(), replacement.token());
    assert!(!writer.unpublish(first));
    writer.release(first);
    assert_eq!(
        read(&index, &query(b"replacement")),
        Ok((b"new".to_vec(), replacement.token()))
    );
}

#[test]
fn foreign_allocation_handles_cannot_release_a_different_extent() {
    for left_length in [40, 8] {
        let (_left_index, mut left) = fixture();
        left.store(&vec![1; left_length]).unwrap();
        let foreign = left.store(&[2; 8]).unwrap();
        let (right_index, mut right) = fixture();
        right.store(&[3; 8]).unwrap();
        right.release(foreign);
        let local = right.store(&[4; 8]).unwrap();
        assert_eq!(local.version, foreign.version);
        if left_length == 8 {
            assert_eq!(local.token(), foreign.token());
        } else {
            assert_ne!(local.at, foreign.at);
        }
        right.publish(&query(b"local"), local).unwrap();
        assert!(!right.unpublish(foreign));
        assert_eq!(
            right.publish(&query(b"foreign"), foreign),
            Err(Refusal::Dead)
        );
        assert_eq!(right.snapshot_copy(foreign), None);
        right.release(foreign);
        assert_eq!(right.snapshot_copy(local), Some(vec![4; 8]));
        assert_eq!(
            read(&right_index, &query(b"local")),
            Ok((vec![4; 8], local.token()))
        );
    }
}

#[test]
fn a_large_free_bin_splits_without_disturbing_live_neighbors() {
    for original_length in [32_768, 3 * 1024 * 1024] {
        let (index, mut writer) = sized_fixture(8, block_words(original_length) + 256);
        let original = writer.store(&vec![1; original_length]).unwrap();
        let keeper = publish(&mut writer, b"keeper", &[2; 120]);
        writer.release(original);
        for length in [200, 20_000] {
            let payload = vec![3; length];
            let reused = writer.store(&payload).unwrap();
            assert_eq!(reused.at, original.at);
            assert_eq!(writer.snapshot_copy(reused), Some(payload));
            assert_eq!(writer.snapshot_copy(original), None);
            assert_eq!(
                read(&index, &query(b"keeper")),
                Ok((vec![2; 120], keeper.token()))
            );
            writer.release(reused);
        }
    }
}

#[test]
fn reusing_a_bin_head_preserves_the_other_free_extents() {
    let (_index, mut writer) = sized_fixture(8, 64);
    let blocks: Vec<Block> = (0..4)
        .map(|value| writer.store(&[value; 120]).unwrap())
        .collect();
    writer.release(blocks[0]);
    writer.release(blocks[2]);
    let first = writer.store(&[4; 120]).unwrap();
    let second = writer.store(&[5; 120]).unwrap();
    assert_eq!(writer.snapshot_copy(first), Some(vec![4; 120]));
    assert_eq!(writer.snapshot_copy(second), Some(vec![5; 120]));
    assert!(writer.store(b"overflow").is_none());
}
