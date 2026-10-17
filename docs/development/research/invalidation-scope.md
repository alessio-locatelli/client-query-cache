# Invalidation scope under interleaved writes

Owner-filtered `find_one` reads can depend on one `_id` even when their filter has additional predicates. Does using the document guard retain useful hits under write churn, and how much of the broader collection-invalidation problem remains?

## Workload and reproduction

The standalone [harness](https://github.com/alessio-locatelli/client-query-cache/blob/main/research/invalidation_scope/benchmark.py) uses a `mongo:8.0.4-noble` single-member replica set limited to 2 CPUs and 2 GiB, Python 3.14.7 and PyMongo 4.18.2. Each cell reseeds both collections with 20,000 documents, 500 authors, 512-byte bodies and an `(author_id, created descending)` index. Document `i` belongs to author `i % 500`. Reads cycle over 32 hot authors and four classes: a newest-20 feed, an author count, `find_one({"_id": a, "author_id": a})` (`own`), and `find_one({"_id": a})` (`by_id`).

A measured cell runs 4,096 reads after 512 warm-up reads. Every 100 or 10 reads, a seeded sequence either inserts a new author's newest document or increments `views` on a uniformly drawn seeded document. The seed is `f"{mix}-{reads_per_write}-{rep}"`. Each of three repetitions runs direct PyMongo, the cache, and an ideal bound that writes to a sibling collection while retaining the same stream event load. Path order reverses on odd repetitions. Direct reads use primary preference and majority read concern, matching eligible cache misses.

Run these commands on the baseline revision and again on the implementation revision, replacing `before` with `after`. The baseline is commit `206ffeb`, which adds the harness without changing runtime routing.

```bash
bash -c 'set -euo pipefail; source scripts/testcontainers-bridge.sh; PYTHONPATH="$PWD" uv run python research/invalidation_scope/benchmark.py run --reps 3 --out /tmp/agents/invalidation-scope/before-run.json; PYTHONPATH="$PWD" uv run python research/invalidation_scope/benchmark.py micro --out /tmp/agents/invalidation-scope/before-micro.json'
PYTHONPATH="$PWD" uv run python research/invalidation_scope/benchmark.py simulate
```

Raw outputs stay untracked. The harness measures process and container CPU, RSS, per-class P50/P95/P99 latency, cache counters and resident-BSON changes, and logical event bytes and invalidations. Driver read counts provide per-class hit shares without snapshots in the measured loop and reconcile with manager misses plus bypasses. Every path records read-start and write-return timestamps. After the cache loop drains all writes, their ordered stream apply timestamps identify reads exposed to a returned but unapplied result-changing write under the exact policy below. Exposure bounds possible stale hits from above; it does not assert that every exposed read hit stale data.

## Live results

Measurements were collected on 2026-10-11. Table values are medians of three repetitions, shown as **before / after**. Throughput includes interleaved write latency. CPU is microseconds per measured read, including writes and stream work during the loop. Direct-path changes illustrate host variability and prevent treating the throughput difference as a controlled production speedup.

| Mix    | Reads/write | Path   |       Reads/s | Client CPU µs/read | MongoDB CPU µs/read |
| ------ | ----------: | ------ | ------------: | -----------------: | ------------------: |
| insert |         100 | direct |   2336 / 1948 |          143 / 175 |           167 / 217 |
| insert |         100 | cache  |   1559 / 2243 |          293 / 185 |           229 / 130 |
| insert |         100 | ideal  |  9920 / 12567 |            55 / 49 |             15 / 18 |
| insert |          10 | direct |   1253 / 1261 |          204 / 196 |           291 / 296 |
| insert |          10 | cache  |    996 / 1126 |          358 / 337 |           347 / 332 |
| insert |          10 | ideal  |   2268 / 2120 |          146 / 152 |           117 / 132 |
| update |         100 | direct |   2222 / 2160 |          147 / 166 |           175 / 192 |
| update |         100 | cache  |   1814 / 2330 |          266 / 189 |           211 / 139 |
| update |         100 | ideal  | 11204 / 12372 |            51 / 49 |             14 / 13 |
| update |          10 | direct |   1335 / 1214 |          188 / 203 |           265 / 296 |
| update |          10 | cache  |   1104 / 1275 |          318 / 293 |           314 / 284 |
| update |          10 | ideal  |   2227 / 2078 |          148 / 144 |           126 / 124 |

Per-class observed cache hit shares, also before / after:

| Mix    | Reads/write |      Feed % |     Count % |         Own % |         By ID % |
| ------ | ----------: | ----------: | ----------: | ------------: | --------------: |
| insert |         100 | 4.88 / 4.88 | 4.88 / 4.88 | 4.88 / 100.00 | 100.00 / 100.00 |
| insert |          10 | 0.49 / 0.49 | 0.49 / 0.49 | 0.49 / 100.00 | 100.00 / 100.00 |
| update |         100 | 4.88 / 4.88 | 4.88 / 4.88 | 4.88 / 100.00 | 100.00 / 100.00 |
| update |          10 | 0.49 / 0.49 | 0.49 / 0.49 | 0.49 / 100.00 | 100.00 / 100.00 |

Every cache cell met the planned comparisons: `own` rose from below 5% hits to within two percentage points of `by_id`; feed and count stayed within two points of their baseline shares. The sibling-write path retained 100% hits in every class. These observed shares differ from the synchronous model because stream invalidation arrives asynchronously.

Per-class P50 latency at 100 reads/write, in microseconds before / after:

| Mix    | Path   |      Feed |     Count |       Own |     By ID |
| ------ | ------ | --------: | --------: | --------: | --------: |
| insert | direct | 313 / 356 | 375 / 465 | 278 / 325 | 223 / 246 |
| insert | cache  | 669 / 562 | 627 / 484 |  464 / 60 |   47 / 23 |
| insert | ideal  |   79 / 58 |   36 / 27 |   35 / 31 |   24 / 17 |
| update | direct | 315 / 332 | 382 / 414 | 281 / 296 | 224 / 230 |
| update | cache  | 571 / 588 | 520 / 505 |  392 / 62 |   40 / 23 |
| update | ideal  |   62 / 58 |   28 / 27 |   27 / 31 |   19 / 17 |

Across individual cells and read classes, the largest exposure share was 0.098% before and 0.098% after. Anchored `own` and `by_id` reads had zero exposed reads in both runs. This workload rarely updates their IDs; the integration tests separately exercise writes that change their results.

RSS ranged from 65–68 MiB before and 65–91 MiB after. Each invalidating cache cell processed exactly its scheduled write count (40 or 409); sibling writes caused no invalidations of cached namespaces. Logical event bytes measure projected BSON events, not compressed network traffic.

The before cache run recorded a median 341 logical event bytes per write.

The after cache run recorded a median 341 logical event bytes per write.

## Warm-hit cost

The `micro` subcommand measures five batches of 20,000 hits per filter without writes. The initial measurement showed a 9.9% plain-ID slowdown, so it was repeated without concurrent validation work against the baseline source in an isolated worktree. Two sequential pairs, with revision order reversed for the second pair, did not reproduce that regression. Generic and plain-ID hits were within the planned 5% ceiling in both pairs. Host variability is visible in the baseline medians, so these samples support the absence of a repeatable regression rather than a speedup claim.

Median microseconds per hit, before / after:

| Measurement                |      Plain ID |  Anchored own | Generic author |
| -------------------------- | ------------: | ------------: | -------------: |
| Initial                    | 16.06 / 17.64 | 24.10 / 27.85 |  22.29 / 21.66 |
| Idle, baseline first       | 18.00 / 16.18 | 23.85 / 31.23 |  22.86 / 21.92 |
| Idle, implementation first | 15.29 / 15.28 | 23.53 / 26.77 |  21.73 / 21.48 |

Anchored hits build a discriminator that includes their additional predicates, while a plain-ID hit reuses the default shape. They cost more than a warm generic author lookup in these samples, but survive unrelated writes. The measured workload demonstrates the resulting hit-rate benefit.

Reproduce the isolated comparison by running `micro` sequentially on each revision with no other checks running, then reversing revision order. Use the same harness and topology on both revisions.

## Find miss cost

[Issue #258](https://github.com/alessio-locatelli/client-query-cache/issues/258) was evaluated on 2026-10-17 against main commit `355a6bd`, using the topology and seeded feed described above. The `find-cost` subcommand separates miss cost from hit-rate changes. Each repetition measures 1,024 direct reads, 1,024 forced misses, 4,096 exact hits, and 4,096 compatible hits supplied by limit-40 sources. Authors cycle over the same 32 hot keys. Phase order reverses on odd repetitions. Forced misses advance the core's write generation before each timed read, preserving warm collection metadata; invalidation, correctness assertions, and the separate 128-miss profile are outside the timing samples. Driver commands and cache counters verify every miss and hit.

Two baseline/corrected-candidate pairs each ran five repetitions per phase with no concurrent validation work. Revision order was baseline first in pair 1 and candidate first in pair 2. Values below are medians of the per-repetition mean microseconds, shown as **baseline / candidate**.

| Pair | Read phase     |      Client CPU |       Wall time |
| ---: | -------------- | --------------: | --------------: |
|    1 | Direct PyMongo | 105.96 / 109.51 | 159.85 / 173.02 |
|    1 | Forced miss    | 283.84 / 242.39 | 371.61 / 313.05 |
|    1 | Exact hit      |   50.43 / 49.31 |   50.23 / 49.07 |
|    1 | Compatible hit |   60.11 / 59.28 |   59.92 / 59.04 |
|    2 | Direct PyMongo | 129.43 / 123.74 | 203.25 / 204.17 |
|    2 | Forced miss    | 288.08 / 250.13 | 377.84 / 325.49 |
|    2 | Exact hit      |   50.41 / 50.12 |   50.15 / 49.92 |
|    2 | Compatible hit |   59.98 / 59.47 |   59.79 / 59.21 |

Miss CPU fell 13–15% and wall time fell 14–16%; neither warm phase regressed. Direct-read variability limits the precision of these local observations, but the miss improvement repeated with revision order reversed. In pair 1's separate profile, cumulative document-capture time fell from 24 ms to 14 ms across 128 misses. Captured documents are encoded inside the existing BSON envelope and their embedded bytes are sliced out without inflating the wrapper. Embedded encoding preserves field order, including a non-leading `_id`; top-level encoding would move `_id` to the front. Final list encoding retains raw snapshots without replaying application codecs. Eligible executions reuse one prepared final discriminator through lookup and admission, and capture reads its immutable size limit without collecting statistics. The remaining profile is dominated by native reads and cursor setup. A miss still costs more than direct PyMongo.

The original three-repetition churn matrix compared main with the initial candidate `2a3bf7a`; it was not repeated for the field-order correction. Feed hit shares remained 4.88% at 100 reads/write and 0.49% at 10 reads/write for both write mixes. Median cache process CPU per read, including writes and stream work, changed from 129.8 to 127.3 µs for insert/100, 404.4 to 358.3 for insert/10, 127.5 to 114.4 for update/100, and 387.7 to 384.5 for update/10. Those initial observations separate miss cost from hit-rate improvement; interleaved write latency and host variation limit end-to-end comparisons.

Reproduce with the same version of the harness on both library revisions, using the existing testcontainers bridge. The baseline checkout needs the `find-cost` harness addition from this change, without its runtime edits. Run each command sequentially and replace `before` with `after` for the candidate:

```bash
bash -c 'set -euo pipefail; source scripts/testcontainers-bridge.sh; PYTHONPATH="$PWD" uv run python research/invalidation_scope/benchmark.py find-cost --reps 5 --out /tmp/agents/find-miss-258/before-cost.json'
bash -c 'set -euo pipefail; source scripts/testcontainers-bridge.sh; PYTHONPATH="$PWD" uv run python research/invalidation_scope/benchmark.py run --reps 3 --out /tmp/agents/find-miss-258/before-churn.json'
```

The `find-cost` output includes the separate cold profile. Raw measurements remain untracked. The 225 existing capture/cursor correctness cases took 46.25 seconds on main and 45.86 seconds on the corrected candidate, with process CPU changing from 11.89 to 11.53 seconds. Four new aggregation field-order cases run separately for dict and SON in both cursor APIs; the existing codec cases now also include a non-leading `_id`. Public cursor behavior, snapshot isolation, complete-consumption admission, exact entry-size enforcement, and generation/availability guards retain their existing tests. These results cover one local synchronous process; both cursor APIs share the optimized key and capture code, but asyncio and production speedups are not quantified here.

## Modeled policies

The simulator replays the same seeded read/write sequences with synchronous invalidation and initially warm keys. All policies invalidate `by_id` only when its document is updated. `current` invalidates the other classes on every write. `id_anchor` treats `own` like `by_id`. `insert_partition` narrows feed/count inserts to their author but keeps updates collection-wide. `field_dependency` retains counts through `views` updates. `all` combines those three rules. `exact` tracks each hot author's 20 newest documents: inserts invalidate that author's feed/count, and updates invalidate its feed only while the updated document is in the current feed.

Overall hit shares, averaged across the three sequences:

| Policy           | Insert 100 | Insert 10 | Update 100 | Update 10 |
| ---------------- | ---------: | --------: | ---------: | --------: |
| current          |     26.83% |    25.20% |     26.83% |    25.20% |
| id_anchor        |     51.22% |    50.15% |     51.22% |    50.15% |
| insert_partition |     75.48% |    73.86% |     26.83% |    25.20% |
| field_dependency |     26.83% |    25.20% |     51.22% |    50.12% |
| all              |     99.87% |    98.81% |     75.61% |    75.07% |
| exact            |     99.87% |    98.81% |     99.98% |    99.77% |

## Scope and alternatives

`find_one` filters that pin an exact `_id` under simple collation retain their cached results through writes to other documents, including owner/tenant predicates. Qualifying unique-index `find_one` reads also use per-document invalidation. Other eligible `find_one` queries and every `find`, `aggregate`, `count_documents`, `distinct` and `estimated_document_count` result still refresh after any collection write. Additional predicates stay in the server query and distinguish cache entries. All paths retain eventual consistency.

The [stream-assisted invalidation evaluation](stream-assisted-invalidation.md) records measured projection costs and the outstanding net-benefit evaluation for insert partitions and update field dependencies. Tracking result IDs alone misses inserts, membership changes and pagination effects. Images add storage/DDL cost; `updateLookup` adds per-event I/O and can observe a later state. Finite `$in` identity sets add variable-size guards and cursor integration without measured demand. TTL does not provide invalidation. Extending anchoring to other read methods or `$eq` spelling lacks usage evidence.

[Find miss cost](#find-miss-cost) records the separate miss-path optimization. Namespace-guarded reads remain cold under churn, so narrowing `own` does not eliminate their miss cost.

These are single-process, closed-loop, local-container observations. They do not measure open-loop capacity, production latency or multi-worker scaling. The [concurrent worker workload study](concurrent-worker-workload.md) holds the open-loop multi-worker evidence, tracked by [#197](https://github.com/alessio-locatelli/client-query-cache/issues/197).
