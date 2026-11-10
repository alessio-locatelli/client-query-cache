# Selective invalidation ownership

The behavioral contract is the `selective-invalidation` OpenSpec capability.
Public configuration and query eligibility belong in the
[API reference](../user/reference/api.md#selective-invalidation).

`local_cache.rs` owns resident nodes and captures under its existing state mutex.
Its lazily allocated selective registry holds at most 1,024 groups across the
manager, including groups held only by in-flight captures. Each group belongs to
a non-reused namespace identity and contains an optional canonical scalar
partition and an optional count-dependency signature. Scalar partitions reuse
identity canonicalization, with a bounded BSON scalar envelope for native
comparison; strings contain at most 64 UTF-8 bytes. Signatures contain at most
32 paths of 64 UTF-8 bytes each. Native boundary checks bound stored descriptors.

Resident and capture references determine reclamation. Eviction, replacement,
namespace clear/drop, and close release resident references. Capture release and
Rust `Drop` release reservations idempotently, including unreachable partially
consumed cursors. At capacity, a group with no active captures and only invalidated
residents can relinquish its metadata; its obsolete rows retain their normal LRU
lifetime. Group identities are never reused, so later row removal or lookup cannot
affect a replacement group. Detached captures continue to occupy capacity after a namespace
is dropped; a new namespace cannot reuse their identity. There is no Python
destructor or auxiliary lease registry. Python equality, codecs, and reference
destruction retain the existing pin/revalidation and retirement boundaries outside
the state mutex. Partition indexes select matching and unpartitioned groups on
known inserts; updates inspect bounded namespace-local groups. Unknown events
advance a namespace fallback fence. Ordinary write generations advance separately.
Ordinary find sources keep their existing per-write clearing. Selective find
sources live in the lazy registry and share its row ownership; compatible lookups
merge both indexes and preserve the smallest valid covering source.

The common pipeline compiler emits `partition: {known: true, value: ...}` only for
configured insert operations, and `changes: {known: true, names: [...]}` only for
configured updates. Unproved hints contain only `{known: false}`. Other events
omit those fields. Changed names combine updated keys, removed fields, and
truncated arrays; missing components, overflow, numeric paths, or nonempty
disambiguation metadata prevent an independence proof. Updated values and full
documents are omitted. Supervisors reuse the compiled pipeline when reopening.

[Real-server regressions](../../tests/test_selective_reads.py) qualify scalar and
UTF-8 boundaries, dependency paths, sparse/partial hinted counts, effective
collation, mixed-policy projection, bounded updated-value payloads, ambiguous
paths, recovery, and cursor disposal using raw reads and drained event positions.
[Native-owner tests](../../tests/core/test_selective_native.py) cover guard
admission, generated operation schedules, lifecycle changes, global capacity,
reentrancy, and reclamation through the production owner.

Run the focused production comparisons from a release installation. The runner
uses public managers and observes routing without replacing its decisions. Its
independent result oracle rejects stale results after the relevant event has been
applied; earlier stale reads remain subject to the normal consistency contract.
Historical experimental paths belong to the revisions recorded in the existing
[research reports](../../research/invalidation_scope/), rather than this runtime.

```bash
source scripts/testcontainers-bridge.sh
python -m research.invalidation_scope.end_to_end --suite micro --reps 4 --micro-reads 10000 --out /tmp/agents/selective-micro.json
python -m research.invalidation_scope.end_to_end --suite churn --paths production --policies disabled insert --mixes insert --reps 4 --out /tmp/agents/selective-insert.json
python -m research.invalidation_scope.end_to_end --suite churn --paths production --policies disabled counts --mixes update --reps 4 --out /tmp/agents/selective-counts.json
python -m research.invalidation_scope.end_to_end --suite churn --paths production --policies disabled both --mixes mixed --reps 4 --out /tmp/agents/selective-both.json
python -m research.invalidation_scope.end_to_end --suite controls --paths production --policies disabled insert counts both --reps 4 --seconds 2 --out /tmp/agents/selective-controls.json
python -m research.invalidation_scope.memory --rounds 16 --out /tmp/agents/selective-memory.json
```

Each output path must be new. Keep raw output untracked. Compare `main` and the
candidate with the same runner and interpreter version, reversing their order in
alternate blocks. Run existing tests separately from the new regressions.
