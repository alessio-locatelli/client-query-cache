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

## Production performance evidence

Measurements compare release builds of `main` (`fdb8cfdd`) and the candidate
(`66928ae0`), using CPython 3.15.1, PyMongo 4.19.0, and the repository-pinned
MongoDB 9.0.4 image. The replica has two CPUs and 4 GiB RAM, without TLS or
compression. The client uses one fixed CPU and hash seed 257. Telemetry is on.
The production runner uses public managers and observes routing without replacing
its decisions. Each block starts from a seeded dataset; four blocks reverse
policy order. Churn cells perform 4,096 reads at 10 or 100 reads per write, with
200 B, 2 KB, and 20 KB documents.

The table gives reductions relative to disabled policies. CPU and elapsed ranges
span the three document sizes' median paired reductions; native-read and total-TCP
ranges span individual cells. Client and server CPU are separate measurements.

| Policy / write mix | Reads per write | Client CPU | Server CPU |    Elapsed | Native reads |  Total TCP |
| ------------------ | --------------: | ---------: | ---------: | ---------: | -----------: | ---------: |
| Insert / inserts   |              10 | 46.8–55.4% | 47.6–62.1% | 31.6–40.0% |   96.6–98.2% | 85.2–96.2% |
| Insert / inserts   |             100 | 79.8–82.0% | 89.3–92.1% | 81.9–84.4% |   99.5–99.9% | 98.2–99.7% |
| Counts / updates   |              10 | 15.5–24.2% | 24.0–31.8% | 16.5–19.4% |   49.9–50.1% |  0.2–10.6% |
| Counts / updates   |             100 | 27.1–42.3% | 44.7–59.6% | 29.2–57.7% |   48.7–51.3% | −1.0–12.1% |
| Both / mixed       |              10 | 14.5–20.6% | 24.3–30.6% | 14.9–22.1% |   49.3–49.7% |  0.4–10.8% |
| Both / mixed       |             100 | 46.8–57.7% | 61.7–72.2% | 51.0–68.4% |   69.8–71.6% | 40.5–49.5% |

Representative 2 KB cells show the latency distribution rather than just saved
commands. Values below are medians of the four cells' quantiles, in microseconds;
each pair is disabled → enabled. They are observations, not latency guarantees.

| Policy / reads per write |        Feed P50 |            Feed P99 |      Count P50 |         Count P99 |
| ------------------------ | --------------: | ------------------: | -------------: | ----------------: |
| Insert / 10              |  589.58 → 79.79 | 1,522.13 → 1,222.17 | 512.83 → 19.65 |   943.64 → 799.07 |
| Insert / 100             |  430.37 → 27.70 |   1,536.11 → 156.54 |  408.44 → 7.32 |    899.02 → 34.42 |
| Counts / 10              | 652.02 → 611.95 | 1,792.69 → 1,716.67 | 542.90 → 26.44 |  1,436.23 → 58.87 |
| Counts / 100             | 450.69 → 390.80 | 1,427.65 → 1,416.44 | 425.67 → 18.43 |  1,062.75 → 51.41 |
| Both / 10                | 595.64 → 628.65 | 1,742.48 → 1,807.82 | 517.09 → 26.39 | 1,231.39 → 370.53 |
| Both / 100               | 439.50 → 373.61 | 1,454.18 → 1,266.95 | 413.80 → 17.05 |  1,162.88 → 47.60 |

Counts-only policies retain counts while feeds still invalidate on updates. Feed
transport can dominate total bytes, and the counts/100 cells include a 1% TCP
increase. Both/10 also has higher median feed quantiles despite lower aggregate
CPU and elapsed time. These measurements do not establish an improvement for
every metric or every read kind.

### Costs and acceptance

The ordinary-sibling control writes to a configured collection while reading an
ordinary cached sibling once per write. At 100 updates/second for eight seconds,
both options increased client CPU in all four blocks by 4.0–7.8% and server CPU
by 4.7–26.0%. Median increases were 6.6% and 10.4%. The additional client work was
36–67 microseconds per update, or approximately 0.36–0.67% of one CPU at this
rate. Routing CPU increased from 28–30 to 57–59 microseconds per update. No native
reads were needed. This isolates a real cost of projected update proofs and their
processing even when the sibling reader cannot benefit.

Logical projected events grew by 47 bytes per update and 35 bytes per insert in
these fixtures. Unconfigured namespaces omit the optional hint fields. Logical
BSON bytes are reported separately from total client TCP traffic, which includes
the normal driver's stream traffic. Uncached-namespace event bytes are encoded
after the timed interval; tracked events reuse the manager's telemetry counts.
The normal controls also cover uncached namespaces and opposite-operation
policies, at 10 and 100 writes/second.

The maintainer explicitly approved these measured opt-in costs on 2026-11-10,
satisfying D6 and completing task 4.2. The approval covers the reported trade-offs;
it does not establish an improvement for metrics with inconclusive measurements.

### Default-path controls and correctness

Whole-process warm comparisons showed order and process variation, so an
additional runner alternates short warm batches between two persistent release
workers on the same CPU. Four blocks of 100 batches of 1,000 reads compare both
identical baseline builds (A/A) and baseline/candidate builds. All samples are
cache hits with zero native commands. The candidate at `cfebe270` has the same
warm-hit path as `66928ae0`; subsequent preparation changes affect misses only.
For feed, prefix, and own-read CPU, A/A ratios span 0.975–1.028, and candidate/base
ratios span 0.969–1.012. These mixed directions characterize variation; they do
not prove absence of a regression or support a warm-hit improvement claim.

Final disabled-policy miss comparisons use `66928ae0`, four counterbalanced
blocks, 2 KB documents, mixed writes, and 10 reads per write. Identical-build
client CPU ratios range from 0.826 to 1.016; candidate/base ratios range from
0.951 to 1.166. The isolated candidate slowdown overlaps substantial process
variation and needs no claimed acceptance benefit. Source inspection establishes
that unconfigured reads skip selective analysis and unconfigured events skip
optional payload processing. Conditional server dispatch is included in the
measured controls, rather than assumed free.

Existing-test comparisons use the same 1,168 baseline tests in both release
environments, separately from new tests, with order and CPU assignments swapped.
Baseline A/A elapsed times on CPU 0 were 7.02–7.19 seconds and on CPU 2 were
9.31–9.41 seconds. Matched baseline/candidate times were respectively
7.03–7.06 / 6.94–7.00 seconds on CPU 0 and 9.30–9.31 / 9.23–9.41 seconds on CPU 2.
The core difference is larger than the candidate difference. New real-server
selective tests took 29.24 seconds for 168 cases, native-owner tests 1.96 seconds
for 26 cases, and production-runner qualification 8.95 seconds for four cases;
these include fixture costs and are reported separately.

Every result checked after its relevant event was applied matched the independent
oracle, and native command/event counts reconciled. Reads before event application
remain subject to normal consistency: the insert matrix recorded 70 such stale
reads, and the counts-policy/opposite-operation control recorded 15. Other final
matrix/control suites recorded none. There is no added runtime barrier.

Sixteen memory rounds exercise 64 namespaces, 1,280 simultaneous captures, 4,096
write-only partition values, drop with captures alive, and later reclamation.
Exactly 1,024 captures acquire selective guards; the remaining 256 use ordinary
fallbacks. Both unbounded and 64-entry caches are tested with one and 32 dependency
paths. Resident BSON peaks at 12,288 and 768 bytes respectively and reaches zero
after drop. Released RSS settles at approximately 49.25 MiB for one path and
52.44 MiB for 32 paths; unbounded cases grow by 24 KiB during allocator warmup
and plateau in the final rounds. No write-value history is retained.

### Reproduction

Use locked release installations for both revisions and the same runner checkout.
Keep raw output untracked; each output path must be new. The image and resource
limits are recorded by the runner. Historical experimental paths belong to the
revisions recorded in the existing [research reports](../../research/invalidation_scope/).

```bash
source scripts/testcontainers-bridge.sh
export PYTHONHASHSEED=257
client_cpu="$(.venv/bin/python -c 'import os; print(min(os.sched_getaffinity(0)))')"
taskset -c "$client_cpu" .venv/bin/python -m research.invalidation_scope.end_to_end --suite churn --paths production --policies disabled insert --mixes insert --reps 4 --out /tmp/agents/selective-insert.json
taskset -c "$client_cpu" .venv/bin/python -m research.invalidation_scope.end_to_end --suite churn --paths production --policies disabled counts --mixes update --reps 4 --out /tmp/agents/selective-counts.json
taskset -c "$client_cpu" .venv/bin/python -m research.invalidation_scope.end_to_end --suite churn --paths production --policies disabled both --mixes mixed --reps 4 --out /tmp/agents/selective-both.json
taskset -c "$client_cpu" .venv/bin/python -m research.invalidation_scope.end_to_end --suite controls --paths production --policies disabled insert counts both --reps 4 --seconds 2 --out /tmp/agents/selective-controls.json
taskset -c "$client_cpu" .venv/bin/python -m research.invalidation_scope.end_to_end --suite controls --paths production --policies disabled both --mixes update --scenarios unrelated --ratios 100 --reps 4 --seconds 8 --out /tmp/agents/selective-update-cost.json
taskset -c "$client_cpu" .venv/bin/python -m research.invalidation_scope.end_to_end --suite controls --paths production --policies disabled insert --mixes update --scenarios cached --reps 4 --seconds 8 --out /tmp/agents/selective-insert-opposite.json
taskset -c "$client_cpu" .venv/bin/python -m research.invalidation_scope.end_to_end --suite controls --paths production --policies disabled counts --mixes insert --scenarios cached --reps 4 --seconds 8 --out /tmp/agents/selective-counts-opposite.json
.venv/bin/python -m research.invalidation_scope.memory --rounds 16 --out /tmp/agents/selective-memory.json
.venv/bin/python -m research.invalidation_scope.paired --base-python /path/to/main/.venv/bin/python --head-python .venv/bin/python --reps 4 --batches 100 --reads 1000 --out /tmp/agents/selective-paired.json
```

Repeat the paired command with the baseline interpreter in both positions for
A/A. For disabled miss comparisons run `--suite pilot --paths production --policy
disabled --sizes 2000 --mixes mixed --ratios 10 --reads 4096 --reps 1` with each
interpreter, reversing order over four blocks; repeat with the baseline interpreter
in both positions. Run existing tests from the baseline checkout with each
release environment selected by `VIRTUAL_ENV`, using
`uv run --active --no-sync -- pytest tests/core tests/synchronous/test_manager.py
tests/asynchronous/test_manager.py -m unit -n 0 --hypothesis-seed 257
--log-file=/dev/null`. Repeat with two baseline environments and swap core/order
assignments. This holds the test corpus constant and avoids collecting new tests.
