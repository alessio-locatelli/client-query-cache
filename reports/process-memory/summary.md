# Process memory beyond the cache budget

The October 10–11 sections preserve the historical measurements and names. See the [November 3 qualification](#retention-safeguards-qualification-on-2026-11-03) for the current optional retention limits and their measured costs.

Measured on 2026-10-10 and 2026-10-11 with CPython 3.14.7 (pymalloc), PyMongo 4.18.2, psutil 7.2.2, and MongoDB 8.0.4 (`mongo:8.0.4-noble`, single-member replica set), on Linux 7.2.9 with an AMD Ryzen 3 210 (8 logical CPUs) and rootless Podman. Measured processes ran with glibc 2.39 from the Ubuntu 24.04 user space of the `mongo:8.0.4-noble` image.

`shared_budget_bytes` and `max_entry_bytes` bound stored and captured BSON. This report measures how much process memory a cache-enabled application uses beyond the same reads without the cache, and classifies each cost. It complements the [Memray churn tier](../../docs/development/memory-regression-tests.md), the [cursor allocation report](../cached-read-cursors/summary.md), the [filter normalization report](../query-filter-normalization/summary.md), and the group PSS figures of the [shared worker cache study](../../docs/development/research/shared-worker-cache-feasibility.md); it does not repeat their allocation measurements.

## Reproduce

Use the [contributor environment](../../CONTRIBUTING.md) with the Podman socket enabled:

```bash
source scripts/testcontainers-bridge.sh
uv run -- python -m research.process_memory.measure run --image docker.io/library/mongo:8.0.4-noble --runs 5 --output benchmark-reports/process-memory/final.json
uv run -- python -m research.process_memory.measure summarize benchmark-reports/process-memory/final.json
```

`--scenarios` selects a subset. A full run takes about two hours; raw JSON stays in the ignored `benchmark-reports/` directory. The pre-fix baseline ran the same harness, without the `cycles` scenario, from a disposable worktree of `893c636`, whose `src/` is identical to the parent of the fix.

The compact-key change reran only the scenarios whose keys it changes, in about one hour, and measured key cost without MongoDB:

```bash
uv run -- python -m research.process_memory.measure run --image docker.io/library/mongo:8.0.4-noble --runs 5 --scenarios small-entries large-keys cycles --output benchmark-reports/process-memory/compact-keys.json
uv run -- python -m research.process_memory.measure summarize benchmark-reports/process-memory/compact-keys.json
just pytest -- tests/benchmark/test_namespace_key_cost.py -n 0 -s -q
```

Its baseline is the run of the bookkeeping fix: `src/` did not change between that measurement and the parent of the compact-key change.

## Method

[`research/process_memory/measure.py`](../../research/process_memory/measure.py) seeds one database, then runs every combination of scenario, API (synchronous or asyncio), and mode (direct PyMongo or cached view) as a fresh Python process in its own disposable container, five times in a seeded random order. MongoDB runs in a separate container, so its memory never enters a measured cgroup. Cached and direct processes issue identical reads, and the application keeps no results except where a phase says so. Differences below are cached minus direct for the same run, reported as the median and range of five runs.

Each checkpoint first runs `gc.collect()`, then records:

- RSS, USS, and PSS from `psutil`;
- the phase peak RSS, a kernel high-watermark (`VmHWM`) reset at the start of every phase through `/proc/self/clear_refs`, not a sampled value;
- the container cgroup's `memory.current`, lifetime `memory.peak`, and `anon` and `file` memory;
- the cache snapshot and the number of GC-tracked objects.

After the last phase, `close` measures without the manager (direct processes measure without change), and `trimmed` calls glibc `malloc_trim(0)` to separate memory the C allocator kept for reuse from live memory. The library never calls it.

Scenarios use the default 1 MiB maximum entry size:

| Scenario          | Reads                                                                                                                  | Budget |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------- | -----: |
| `documents`       | `find_one` by `_id` of 4,365–4,371-byte catalogue documents: 14,000 cold, 14,000 warm, 3,920 more cold                 | 64 MiB |
| `result-sets`     | Sorted `find` of 224 such documents (0.93 MiB entries): 64 cold, 64 warm, 16 retained by the application, 16 more cold | 64 MiB |
| `small-entries`   | Generic `find_one` with a one-field filter, 59-byte entries: 64,000 cold, 64,000 warm, 36,000 more cold                |  4 MiB |
| `large-keys`      | As `small-entries`, adding a 48-value `$in` filter built per request                                                   |  4 MiB |
| `partial-cursors` | 32 open sorted `find` cursors that each read 220 of 224 documents, then close                                          | 64 MiB |
| `cycles`          | Five rounds of opening a manager, reading 40,000 distinct small results with eviction, and closing it                  |  1 MiB |

## Results

The tables use the final code. "Δ" is cached minus direct RSS at the checkpoint, as the median and range of five runs. "Growth per entry" subtracts each process's own `baseline` checkpoint first, so it excludes the library and manager, which cost 1.8–2.2 MiB of RSS before the first cached read. Synchronous and asyncio cells agree within 0.1 MiB unless both are shown. Every warm read hit, every cold read missed, and no read bypassed the cache.

### Full budgets

| Scenario                        | Stored BSON | Entries | Δ RSS MiB                                     | Growth per entry | Growth ÷ stored BSON |
| ------------------------------- | ----------: | ------: | --------------------------------------------- | ---------------- | -------------------: |
| `documents`, after eviction     |    64.0 MiB |  15,356 | 74.0 (73.8–74.3)                              | 4,919–4,928 B    |                 1.13 |
| `result-sets`, after eviction   |    63.4 MiB |      68 | sync 68.3 (67.9–69.2), async 65.0 (61.0–65.9) | 0.92–0.97 MiB    |            0.99–1.04 |
| `small-entries`, cold           |     3.6 MiB |  64,001 | sync 48.7 (48.6–48.9), async 48.4 (48.3–48.9) | 764–767 B        |            12.9–13.0 |
| `small-entries`, after eviction |     4.0 MiB |  71,089 | sync 61.0 (61.0–61.3), async 60.8 (60.8–61.3) | 871–873 B        |                 14.8 |
| `large-keys`, cold              |     3.6 MiB |  64,001 | 272.7 (272.4–273.0)                           | 4,435 B          |                 75.2 |
| `large-keys`, after eviction    |     4.0 MiB |  71,089 | 309.1 (308.8–309.4)                           | 4,530 B          |                 76.8 |

Container `memory.current` differences match the RSS differences within 1.2 MiB in every row except the synchronous `small-entries` rows, where three runs' counters already differed by 4.0–6.6 MiB at the `baseline` checkpoint, before the first cached read; `anon` and USS differences match within 0.4 MiB in every row. Absolute container memory followed USS and stayed about 17 MiB below RSS, which also counts the interpreter's and libraries' shared file pages. Phase peaks equal the end-of-phase values except during eviction of small entries, which peaked 1.8–1.9 MiB above the result in both scenarios.

Warm passes added 0.6 MiB for `documents` and 2.2 MiB for the small-entry scenarios, without new entries: hits decode each result into new objects that the reads then discard. `result-sets` warm passes added nothing.

When the application kept 16 decoded results (about 14.9 MiB of BSON), RSS grew by 19.5 MiB in direct processes and by 17.5 MiB in cached ones: the application owns that memory in both modes.

### Open cursors

Thirty-two cursors that each read 220 of 224 documents retained 30,765,770 bytes of captured payload (29.3 MiB). Δ RSS was 34.1 MiB (33.8–34.2) synchronously and 30.6 MiB (30.1–33.2) with asyncio. Closing the cursors left 18.6 MiB (sync) and 30.0 MiB (async) above direct processes; `malloc_trim(0)` then reduced both to about 4.7 MiB.

### Memory after closing

| Scenario        | Δ RSS after closing, sync | Δ RSS after closing, async | After `malloc_trim(0)`, sync / async |
| --------------- | ------------------------: | -------------------------: | -----------------------------------: |
| `documents`     |          19.5 (10.4–19.7) |              7.4 (6.4–7.6) |                            7.7 / 7.6 |
| `result-sets`   |           13.2 (2.5–22.5) |            −0.4 (−4.6–0.7) |                           1.3 / −1.9 |
| `small-entries` |          20.4 (19.7–22.8) |           38.3 (33.8–39.5) |                          20.6 / 31.6 |
| `large-keys`    |          37.3 (35.0–39.6) |           61.5 (49.3–68.3) |                          35.8 / 61.7 |

Each value includes the library's modules, which stay imported after closing. GC-tracked object counts after closing were 21–130 below each process's cached baseline, so no cache objects survived. glibc trimming returns the memory that held stored BSON and captures, which glibc allocates outside Python's small-object allocator. It cannot return memory held by Python's small-object arenas, which stay mapped while any block in them is live; keys, entries, and bookkeeping are small objects, so retention grows with the number of entries rather than with stored bytes.

In `cycles`, five managers in one process each filled a 1 MiB budget with 17,772 small entries and evicted 22,229:

| Cycle | Δ RSS filled, sync / async | Δ RSS closed, sync / async | GC objects after closing, sync / async |
| ----: | -------------------------: | -------------------------: | -------------------------------------: |
|     1 |                16.6 / 16.4 |                11.2 / 13.7 |                        45,979 / 46,324 |
|     2 |                17.6 / 17.7 |                12.3 / 12.9 |                        45,979 / 46,178 |
|     3 |                17.9 / 17.5 |                13.1 / 13.0 |                        45,979 / 46,216 |
|     4 |                17.6 / 17.7 |                13.3 / 13.2 |                        45,979 / 46,266 |
|     5 |                17.9 / 17.7 |                13.3 / 13.2 |                        45,979 / 46,300 |

Filled peaks grew by at most 0.3 MiB after the first cycle and object counts stayed flat, so closed managers release their cache and later managers reuse the retained memory. An exploratory in-process run of 12 cycles of 64,000 small entries on the pre-fix code showed the same plateau, with 19.2 MB in allocated small-object blocks after the last close against 36.5 MB in unused pools of partly used arenas.

### Effect of the bookkeeping fix

The pre-fix baseline repeated every scenario except `cycles`. Its cached processes started about 1.5 MiB higher, most likely because the fresh read-only worktree had no compiled bytecode for the library, unlike the main checkout; growth per entry cancels that difference.

| Scenario                        | Growth per entry, before → after | Growth ÷ stored BSON, before → after | GC objects per entry, before → after |
| ------------------------------- | -------------------------------: | -----------------------------------: | -----------------------------------: |
| `documents`, after eviction     |                  5,139 → 4,928 B |                          1.18 → 1.13 |                                5 → 3 |
| `small-entries`, after eviction |                  1,313 → 1,245 B |                          22.3 → 21.1 |                              12 → 11 |
| `large-keys`, after eviction    |                  5,483 → 5,414 B |                          92.9 → 91.8 |                              23 → 22 |

`result-sets` and `partial-cursors` did not change beyond noise.

### Effect of compact canonical keys

The compact-key change reran only `small-entries`, `large-keys`, and `cycles`, against the run of the bookkeeping fix. `documents`, `result-sets`, and `partial-cursors` keep the figures above: their reads share one default read shape per collection or hold only 68 entries, so their keys do not change measurably.

| Scenario                        | Growth per entry, before → after | Growth ÷ stored BSON, before → after | GC objects per entry, before → after |
| ------------------------------- | -------------------------------: | -----------------------------------: | -----------------------------------: |
| `small-entries`, after eviction |                    1,245 → 873 B |                          21.1 → 14.8 |                               11 → 5 |
| `large-keys`, after eviction    |                  5,414 → 4,530 B |                          91.8 → 76.8 |                               22 → 9 |
| `cycles`, fifth fill            |                    1,303 → 923 B |                          22.1 → 15.6 |                               11 → 5 |

Δ RSS after eviction fell 86.5 → 61.0 MiB for `small-entries` and 369.1 → 309.1 MiB for `large-keys` (synchronous medians). The saving per entry, 372 and 884 bytes, is close to the 376 and 872 bytes of key tuples that the key-cost benchmark attributes.

### Per-entry attribution

`tracemalloc` attribution of 5,000 `_id` entries and 20,000 generic `find_one` entries, admitted after warm-up through the synchronous view, records requested bytes rather than RSS:

| Retained per entry with the final code             | `_id`, 4.4 KB documents | One-field filter | 48-value `$in` filter |
| -------------------------------------------------- | ----------------------: | ---------------: | --------------------: |
| Stored BSON `bytes` object                         |                   4,403 |               92 |                    92 |
| Canonical query key tuples                         |                       – |   272 (4 tuples) |        912 (8 tuples) |
| Identity or filter values                          |                      31 |               49 |                 2,679 |
| Entry, key object, generation guard, LRU and index |               about 310 |        about 290 |             about 290 |
| Identity state and its index                       |               about 125 |                – |                     – |
| Total, including smaller items                     |                   4,896 |              702 |                 4,021 |

The identity value is decoded by the library; filter strings are the objects the application passed in each request.

The key row comes from the key-cost benchmark under [Reproduce](#reproduce), which retains 20,000 generic `find_one` keys built as the synchronous view builds them; the compact-key change took it 648 → 272 bytes (10 → 4 tuples) and 1,784 → 912 bytes (22 → 8 tuples), where the before values equal the full attribution. That change touched no other row's code, so the filter totals are the totals attributed after the bookkeeping fix, 1,078 and 4,893 bytes, minus the measured key saving of 376 and 872 bytes.

Before the bookkeeping fix, each `_id` entry also retained a 216-byte empty alias set and a 72-byte `NamespaceId`, and each generic entry the 72-byte `NamespaceId`.

## Classification

- **Expected object ownership.** Stored BSON lives in Python `bytes` objects with a 33-byte header. Hits decode results into new Python objects, as direct PyMongo reads do, and the application owns any result it keeps. Allocator rounding and size classes add a few percent.
- **Justified trade-offs.** About 0.3 KB per entry for the entry, its key object, its generation guard, and the LRU and reclamation indexes, plus about 0.1 KB of identity state for `_id` entries; this supports exact invalidation, eviction, and namespace reclamation without scanning. Cursor captures keep encoded snapshots plus wrappers, 34.1 MiB of RSS for 29.3 MiB of payload, and release them when a cursor closes.
- **Avoidable duplication.** The bookkeeping fix removed the empty alias set and the per-entry `NamespaceId`, and the compact-key change removed the extra tuple layers that canonical keys wrapped around each order-sensitive node, 6 of 10 key tuples for a one-field filter.
- **Leaks or missing cleanup.** None found. Closing cursors and managers released every cache object, repeated cycles reached a stable peak, and `malloc_trim(0)` recovered the glibc share of freed memory.
- **Capacity considerations.** The BSON budget does not bound memory for small entries or large filters: a 4 MiB budget of 59-byte results cost about 61 MiB, and 309.1 MiB with a 48-value `$in` filter. Open miss cursors add up to their payload plus wrappers. Freed memory stays in the process for reuse, so RSS follows the peak. The [deployment guide](../../docs/user/operations/deployment.md#memory-beyond-the-cache-budget) summarizes these points for users.

Confirmed existing behavior, unchanged here:

- A unique-key match stores one encoded value under two keys and charges its size twice, an [accepted inefficiency of the cache core design](../../openspec/changes/archive/2026-09-10-implement-cache-core/design.md); `used_bytes` then overstates resident payload for such reads.
- Every namespace that a read or a change-stream write touches keeps about 0.6 KB of state until the manager closes, bounded by the number of collections.
- A limited find hit decodes its whole source result before installing the requested prefix, as the [architecture guide](../../docs/development/architecture.md#cursor-driver-integration) documents.

## Limitations

- One host and one run order per run index; process memory varies little between runs, but retention after closing varies with allocation order, as the ranges show.
- glibc 2.39 and CPython's small-object allocator. musl, jemalloc, other glibc versions, or other Python versions can change retention and per-object sizes.
- One document shape. Results with many small fields decode into more Python objects than these string-heavy documents.
- Filters in `large-keys` are built per request, so the key retains their strings. Filters built from shared constants retain fewer objects.
- Checkpoints call `gc.collect()`, so they exclude garbage that an application's collector has not yet reclaimed.
- Container file memory stayed near zero because the host page cache already held the mounted interpreter and libraries. A container image that loads them itself charges those pages to its own counter.
- MongoDB memory is excluded; this report says nothing about server memory.

## Retention safeguards qualification on 2026-11-03

This section records measurements for [issue #337](https://github.com/alessio-locatelli/client-query-cache/issues/337) against the optimized `main`, whose release wheels use fat LTO, a single code generation unit and profile-guided optimization (PGO). The preceding tables describe the October 10–11 implementation and retain its configuration names. The current capacity and sizing contracts are in the [API reference](../../docs/user/reference/api.md#optional-retention-limits).

Summary of the incremental costs against frozen `main`:

- With both limits disabled, the public read paths stay within about 3% of `main`, the spread between independent `main` builds. `CacheSnapshot` construction costs about 9% (0.3 µs) more because it reports four more fields. Three native micro-workloads on code the pull request does not change run up to 3% slower; the instruction streams are identical, and public shared-cache reads and publications, and the public warm hits, show no stable difference ([details](#differences-on-unchanged-code)).
- `max_entries` alone adds no measurable cost to a cache miss or a hit. `max_key_bytes` adds the cost of sizing the key on every admitted miss, 2–5 µs between real requests (about 2–3% of a cold read), and nothing to hits except about 30 ns for unique-key hits with `max_entries` set. The in-process floor and the rejected reductions are in [the admission analysis](#enabled-admission-cost).
- On the workload of issue #337 (small cached results behind long `$in` filters), bounding the entry count to 10,000 cut the memory added by the cache from 297 MiB to 46 MiB, and a 2,048-byte key limit cut it to 5 MiB. Both bounds trade cache coverage for memory; the [workload section](#memory-protection-on-the-issue-337-workload) lists the lost hits and added database queries.
- The example limits of the deployment guide (50,000 entries, 16 KiB keys) leave 212 MiB of that workload's growth, because 50,000 long-filter entries are not a small bound.

### Builds, environment and method

Frozen `main` was `4e071dfd5904527545177cd2e6f5bdb78a2239c9`. The candidate was the pull request's `feat(core)` commit; later commits in the pull request change documentation and the OpenSpec change only. Every wheel came from the project's release pipeline, `just build`, which runs `maturin build --release --pgo --zig` with the training of `scripts/pgo_training.py`. Profile-guided layouts differ between builds of identical source, so the comparisons use independent builds as the noise floor: five builds of `main` (A–E) and five of the candidate (16–20). Each wheel was installed into its own target directory with `uv pip install --no-deps --target`; the processes record the imported extension.

| Build        | Wheel SHA-256                                                      |
| ------------ | ------------------------------------------------------------------ |
| `main` A     | `2960347e762693d70bb639c35c0ee2cf0200d571f78a31aada691a3889f57ddb` |
| `main` B     | `fac23dab77853c27e628d19f3af55b20755926a094ab14fbce2ec825ccf534ad` |
| `main` C     | `ff113d0bbb926885db5f7a11faa75d1569e25ca79c5ed5e0613b7ffec5e1f788` |
| `main` D     | `fa68c4597e33a883383fc01b35a1cbff51a250e5c0866a3cab064f87553911ba` |
| `main` E     | `f5921cadcb584d0711c030610eb341c82fa5a0147b6f20c1a4b7f5ebd9a440c7` |
| Candidate 16 | `6e3c8f800ea7778904e1b7482f4a5540977f8158af72221f3f0881c7669cad7d` |
| Candidate 17 | `93cbfeefaaa4f53bfea213e0a10257eb23b710a17fad85fd1ce8aa3e0610628e` |
| Candidate 18 | `e875f07df62c562a670ecd52bd70823fd340566ab1f8cef6343084f805c27671` |
| Candidate 19 | `4065954d8b936f36f61828f579833934f4ea6fb04c970360ffebb6c1a8df34a8` |
| Candidate 20 | `fae054e9331be60ccac1b2fb1118e786f1bad454fc6fdf6719aa286d833453c6` |

The environment was CPython 3.14.7, PyMongo 4.19.0, psutil 7.2.2, Rust 1.99.1, maturin 1.16.0, Linux 7.2.15 and glibc 2.43 in Fedora Toolbx on an Intel Core i3-13100 (eight logical CPUs). MongoDB was 9.0.4, from `mongo:9.0.4@sha256:dc28ed5a9d0fc616903c3f463bb1e53b92b49f441721b91926e87d90bf957ce8`, in one disposable replica set per acquisition. Measured processes were pinned to CPU 2. During the end-to-end cells a `nice -n 19` busy loop shared that CPU, which keeps its clock and process-CPU accounting stable; wall-clock latency is therefore not reported, and every end-to-end cost below is process CPU per read. Every comparison alternates its builds inside one acquisition.

The measurements use five harnesses:

- **Native workloads.** `research.native_build_profile.compare` runs the 25 native workloads of `scripts/pgo_training.py` that do not need a limit, five rounds in shuffled build order, and compares each build with build A.
- **Admission cost per limit.** `research.native_build_profile.limits` times the native admission and hit paths in-process with no limit, `max_entries` alone, `max_key_bytes` alone and both, using generous limits, and with the count limit at capacity.
- **Public reads.** The `retention-child` cells of `research/process_memory/measure.py`: 8,192 distinct `find_one` reads with a `code` index, a 4 MiB BSON budget and 4,096 retained keys, for the 59-byte results of `small-entries` and the 48-value `$in` filters of `large-keys`. Ten fresh processes per build and cell; forty for the equal-residency cell that isolates each limit. The enabled limits are `max_entries=4096` and `max_key_bytes=2048`, which admits the one-field key and declines the 48-value key.
- **Unique-key, alias and contention cells.** Both APIs also ran a unique-index stream: cold unique-key queries, repeated queries, `_id` reads, a processed unrelated write and a processed matched-identity write. One- and two-slot controls used one distinct query with 4,096 reads per phase; prefilled controls used 128 queries with eight preexisting aliases and 48 or 112 unrelated identity values, against a 128-record limit and 32 passes per phase. A many-to-one control used 128 distinct aliases for one document, against 256 records. Frozen `main` and the disabled candidate received the same requests with no record limit. The cold phases of the one- and two-slot cells contain a single read and are omitted from the comparisons. The core-only controls published and individually removed 256, 1,024 and 4,096 aliases for one identity, with a capture held, three cycles per process; the enabled capacity was the alias count plus two. The contention controls performed 32,768 complete capture, encode and admit operations per thread with one or four threads across two namespaces, a 16 MiB BSON budget and a 131,072-record cap, so every build retained the same records without eviction. They measured the private Python reference core and the public native owner separately; the exported managers use only the native owner. Ten processes per build and cell.
- **Pull-request guard workload.** `research.native_build_profile.end_to_end` alternates builds on `benchmarks.stream_cost.guard_workload` against an isolated replica set, five rounds with the best of three runs per cell.
- **Issue #337 workload.** The `child` scenarios of `research/process_memory/measure.py`, three repetitions per configuration.

### Disabled limits

Both limits are `None`. The first table compares the native workloads: each cell is the median over five rounds of the percentage by which a build is slower than build A (negative means faster), shown as the median and range across the four other builds of `main` and across the five candidate builds. The spread among the `main` builds is the noise floor for build-to-build differences.

| Workload                     | Other `main` builds B–E | Candidate builds 16–20 | Difference of medians |
| ---------------------------- | ----------------------: | ---------------------: | --------------------: |
| `admit_churn_medium`         |     -0.6 (-1.5 to +0.2) |    -1.0 (-1.2 to -0.5) |                  -0.4 |
| `admit_churn_small`          |     -0.0 (-0.4 to +0.9) |    -0.4 (-1.7 to +0.4) |                  -0.4 |
| `capture_array`              |     -0.3 (-0.5 to +0.2) |    +0.4 (+0.3 to +0.8) |                  +0.7 |
| `echo_roundtrip`             |     -0.4 (-1.5 to -0.2) |    -0.2 (-1.1 to +0.4) |                  +0.3 |
| `facade_find_miss`           |     +0.2 (-1.9 to +0.6) |    -1.6 (-3.4 to -0.7) |                  -1.9 |
| `facade_hit`                 |     -0.0 (-0.7 to +0.6) |    -1.3 (-1.3 to -0.6) |                  -1.3 |
| `facade_invalidation`        |     -0.0 (-1.6 to +0.8) |    +1.4 (-0.2 to +1.7) |                  +1.4 |
| `find_exact_hit`             |     -0.5 (-0.8 to -0.3) |    +0.6 (+0.3 to +0.9) |                  +1.0 |
| `find_subsumed_hit`          |     -1.3 (-2.0 to -0.7) |    -0.7 (-2.0 to -0.3) |                  +0.6 |
| `identity_hit_decoded_small` |     -0.7 (-0.8 to -0.7) |    -2.7 (-3.1 to -1.4) |                  -2.0 |
| `identity_hit_medium`        |     +0.4 (-0.7 to +1.6) |    +0.5 (-0.5 to +1.4) |                  +0.2 |
| `identity_hit_small`         |     +0.6 (-0.3 to +1.6) |    +0.4 (-0.3 to +2.0) |                  -0.2 |
| `identity_miss`              |     +0.4 (+0.1 to +0.8) |    +0.4 (-0.1 to +1.8) |                  +0.1 |
| `key_preparation_large`      |     -0.2 (-1.8 to +0.7) |    +0.1 (-0.5 to +0.6) |                  +0.3 |
| `key_preparation_small`      |     +0.1 (-0.5 to +0.1) |    +0.6 (-0.6 to +2.5) |                  +0.5 |
| `namespace_hit`              |     -1.2 (-2.2 to -0.6) |    -0.2 (-0.3 to +0.2) |                  +1.0 |
| `namespace_lifecycle`        |     -0.5 (-0.6 to +0.8) |    -3.1 (-3.4 to -0.1) |                  -2.6 |
| `owner_admission`            |     +0.4 (+0.1 to +1.7) |    +0.3 (-0.8 to +2.5) |                  -0.1 |
| `shared_hit_medium`          |     -1.2 (-2.2 to -0.1) |    +2.0 (+1.4 to +3.1) |                  +3.2 |
| `shared_hit_small`           |     +0.2 (-1.2 to +1.4) |    +1.1 (+0.4 to +2.3) |                  +0.9 |
| `shared_miss`                |     -0.7 (-1.2 to +0.5) |    -0.1 (-0.6 to +0.7) |                  +0.6 |
| `shared_publish_cycle`       |     +0.1 (-3.0 to +0.4) |    +2.4 (+1.1 to +4.1) |                  +2.3 |
| `snapshot`                   |     -1.7 (-2.0 to -1.4) |    +8.2 (+7.8 to +9.7) |                  +9.9 |
| `wire_keys`                  |     +0.2 (-0.4 to +0.4) |    -0.4 (-1.2 to +0.2) |                  -0.6 |
| `write_invalidation`         |     -0.2 (-2.4 to +1.4) |    -2.6 (-2.9 to -1.4) |                  -2.4 |

The geometric mean over the 25 workloads is −0.2% for the other `main` builds and +0.3% for the candidate builds. An exact permutation test over the nine builds finds a candidate difference of +0.6% (p = 0.06), and +0.2% without `snapshot` (p = 0.52). Ten of the 25 workloads differ at p < 0.05, against about one expected by chance: six are slower and four faster in the candidate builds. The report does not credit the faster ones against the slower ones. An A/A control, a second copy of build A measured as its own label, differs from A by up to +3.8% (`find_exact_hit`) in the same acquisition, so differences of about 1% on a single workload are not resolved.

- **`snapshot`, 3.49 → 3.81 µs (+0.32 µs, +9–10%).** The source explains it: the snapshot gained `max_entries`, `max_key_bytes`, `alias_count` and `retention_declines`, and the native call and the Python dataclass carry them. The decline counts are shared tuples that are rebuilt only when a count changes. The cost belongs to the reporting API and is not on the request path.
- **`shared_hit_medium` (+3.2%), `shared_publish_cycle` (+2.3%) and `capture_array` (+0.7%)** run the shared-index reader and publisher and `EncodedArray`, code that the pull request does not change; its only edit in the shared-index sources renames an argument in `shared.rs`. [Differences on unchanged code](#differences-on-unchanged-code) investigates them.
- **`find_exact_hit` (+1.0%) and `namespace_hit` (+1.0%)** are inside the A/A control's own differences (+3.8% and +1.6%) in this acquisition.
- **`identity_hit_decoded_small` (−2.0%), `facade_hit` (−1.3%), `namespace_lifecycle` (−2.6%) and `write_invalidation` (−2.4%)** are faster in the candidate builds.

The profile-guided training decides which functions are optimized for speed: a function whose count falls below the profile's cold threshold is optimized for size. The training therefore covers the new native entry points (see [PGO training coverage](#pgo-training-coverage)), and the [native quality guide](../../docs/development/native-quality.md#release-build) records why its opt-in admission workloads run for a fifth of the default time.

The public end-to-end cells compare `main` with the disabled candidate and with a second independent `main` build. The table shows process CPU in µs per read as the median and range of ten processes, and the paired percentage change against `main` with its bootstrap interval.

| API / filter / phase           | Main                   | Other main build       | Disabled candidate     | Disabled vs main % | Other main build vs main % |
| ------------------------------ | ---------------------- | ---------------------- | ---------------------- | ------------------ | -------------------------- |
| sync / small-entries / cold    | 119.50 (106.94–178.27) | 117.77 (112.24–157.06) | 121.83 (110.38–175.87) | -1.2 [-3.4, +5.9]  | -1.3 [-8.2, +2.3]          |
| sync / small-entries / repeat  | 6.12 (6.01–9.39)       | 6.18 (6.01–9.12)       | 6.22 (6.04–7.16)       | +0.8 [-6.3, +8.2]  | +1.0 [-4.4, +3.3]          |
| sync / large-keys / cold       | 156.75 (145.27–176.72) | 155.09 (142.74–176.89) | 158.17 (142.94–198.43) | +1.8 [+0.0, +9.1]  | -1.0 [-2.1, +2.1]          |
| sync / large-keys / repeat     | 23.22 (21.94–27.93)    | 22.92 (22.16–24.55)    | 23.27 (22.14–23.86)    | -0.6 [-2.6, +1.3]  | -0.2 [-3.0, +1.0]          |
| async / small-entries / cold   | 209.23 (203.07–293.74) | 211.83 (203.93–251.54) | 217.11 (201.87–237.28) | +0.8 [-0.8, +2.8]  | +0.8 [-0.6, +1.9]          |
| async / small-entries / repeat | 6.47 (6.22–7.42)       | 6.54 (6.26–6.67)       | 6.67 (6.40–7.13)       | +2.9 [+0.8, +4.4]  | +0.4 [-4.1, +2.8]          |
| async / large-keys / cold      | 248.33 (236.34–285.81) | 248.32 (231.66–261.05) | 246.72 (230.57–338.62) | +0.2 [-2.3, +2.2]  | -1.5 [-4.8, +1.2]          |
| async / large-keys / repeat    | 23.70 (22.47–25.19)    | 23.43 (22.67–33.20)    | 23.53 (22.33–25.21)    | -0.5 [-2.2, +1.1]  | -1.0 [-3.3, +3.1]          |

Only the asynchronous warm hit of `small-entries` differs from `main` beyond its interval (+2.9% [+0.8, +4.4], 0.2 µs of 6.5 µs), and the second `main` build differs there by +0.4% [−4.1, +2.8]. [Differences on unchanged code](#differences-on-unchanged-code) shows that this difference does not reproduce at the public level with equal-length overlay paths. With limits disabled, the candidate admits and retains exactly what `main` does (8,192 values, 598,016 charged bytes and 8,192 origin queries in every cell).

The pull-request guard workload (percentage slower than `main` build A, median and bootstrap interval over five rounds; negative means faster) shows the same picture. Its `find_admission` cells vary by more than ±10% between rounds for every build, including the second `main` build.

| Workload                |  Other `main` build | Candidate build 16 | Candidate build 17 |
| ----------------------- | ------------------: | -----------------: | -----------------: |
| `async_hit/medium`      |   +1.1 [-8.3, +5.3] |  -2.0 [-7.2, +0.4] | -1.5 [-11.2, +2.1] |
| `async_hit/small`       |   +0.5 [-1.9, +0.9] |  -0.6 [-1.8, +2.5] |  +0.2 [-2.2, +2.0] |
| `find_admission/medium` |  +5.2 [-1.2, +25.3] | +2.0 [+0.3, +15.8] | +7.8 [-4.4, +31.0] |
| `find_admission/small`  | +19.6 [-7.0, +32.4] | +4.9 [-1.8, +15.4] | +0.4 [-7.4, +23.2] |
| `invalidation/medium`   |   +1.4 [-8.0, +3.0] |  -0.3 [-5.9, +1.5] | -2.0 [-10.0, -0.6] |
| `invalidation/small`    |   +2.4 [+0.9, +4.9] |  +0.5 [-1.1, +1.3] |  -0.5 [-2.6, +0.8] |
| `sync_hit/medium`       |   +1.7 [-1.7, +2.5] |  -0.4 [-5.7, +0.2] |  -1.6 [-4.4, +7.3] |
| `sync_hit/small`        |   +0.1 [-1.8, +1.2] |  +0.4 [-9.2, +1.7] |  -0.3 [-9.5, +3.0] |
| geometric mean          |   +2.9 [+0.0, +8.1] |  +0.1 [-1.0, +3.6] |  +0.5 [-1.8, +3.7] |

### Differences on unchanged code

The three workloads above were slower in the candidate builds in each of five acquisitions with the standard harness (difference of medians against the other `main` builds, percent):

| Acquisition (candidate builds) | `shared_hit_medium` | `shared_publish_cycle` | `capture_array` |
| ------------------------------ | ------------------: | ---------------------: | --------------: |
| 1 (builds 5–9)                 |                +3.5 |                   +1.2 |            +1.3 |
| 2 (builds 11–15)               |                +1.6 |                   +1.2 |            +0.7 |
| 3 (builds 16–20, table above)  |                +3.2 |                   +2.3 |            +0.7 |
| 4 (builds 16–20)               |                +1.7 |                   +0.1 |            +0.6 |
| 5 (builds 16–20)               |                +1.0 |                   +1.1 |            +0.5 |

Hardware counters, an instruction trace and the public shared-cache paths explain or bound them. The counters are user-space `perf_event_open` events read from Python, because `perf` was not installed; `perf stat -e instructions:u,cycles:u,branch-misses:u,L1-dcache-load-misses:u` reads the same events. Measured processes were pinned to CPU 2.

**The executed code is the same.** Single-stepping one `ReaderIndex.lookup` call with `ptrace` executes 5,906 instructions in the candidate and in `main`, of which 2,993 are in the extension, 2,141 in CPython and 709 in glibc. The lookup trampoline has 1,423 static instructions in `main` and 1,418 in the candidate; the differences are mostly register allocation.

**The 1.0% instruction gap per read is allocator state, not code.** In the 1,024-read loop `main` retires 4,515 instructions per read and the candidate 4,560. Perturbing the glibc heap before the workload moves the same binary across that whole range and swaps the order of the two builds (instructions per read, `main` build A and candidate build 16):

| Heap perturbation before the workload | `main` | Candidate |
| ------------------------------------- | -----: | --------: |
| none                                  |  4,515 |     4,560 |
| one 1,100-byte object                 |  4,560 |     4,520 |
| 2,200 and 100 bytes                   |  4,515 |     4,576 |
| one 5,000-byte object twice           |  4,515 |     4,495 |
| one 9,000-byte object                 |  4,510 |     4,560 |

**Counters per operation** over three repetitions with five builds per side, with the default glibc allocator and with its heap growth and trim behavior fixed (`MALLOC_TOP_PAD_=16 MiB`, `MALLOC_TRIM_THRESHOLD_=64 MiB`):

| Workload / allocator            | Instructions                    | Cycles                          | Branch misses      | L1D misses                   |
| ------------------------------- | ------------------------------- | ------------------------------- | ------------------ | ---------------------------- |
| `shared_hit_medium`, default    | 4,515 → 4,560 (+1.0%)           | 1,226 → 1,231 (+0.4%, p = 0.18) | 2.97 → 2.72        | 24.4 → 24.9                  |
| `shared_hit_medium`, fixed      | 4,508 → 4,553 (+1.0%)           | 1,214 → 1,214 (−0.0%, p = 0.43) | 2.99 → 2.63        | 21.3 → 24.6 (+15%, p = 0.01) |
| `shared_publish_cycle`, default | 6,570 → 6,563 (−0.1%)           | 1,676 → 1,696 (+1.2%, p = 0.37) | 1.00 → 1.15        | 1.99 → 2.04                  |
| `shared_publish_cycle`, fixed   | 6,538 → 6,563 (+0.4%, p = 0.22) | 1,634 → 1,689 (+3.4%, p = 0.02) | 1.77 → 1.00 (−44%) | 1.98 → 1.92                  |
| `capture_array`, default        | 561.8 → 561.8                   | 288.1 → 288.2 (+0.0%)           | 0.014 → 0.014      | 2.76 → 2.78                  |

**`capture_array` follows glibc's heap trimming.** After `shared_hit_medium` in one process, the candidate builds measure 110 ns against 47 ns for `main` because the process grows and shrinks its heap around every 8 MiB array (4,458 `brk` calls against 104). With a trim threshold of 64 MiB or a heap growth pad of 16 MiB the two agree (48.1 against 47.8 ns). `capture_array` alone, or earlier in a longer workload list, does not enter that state.

**With the allocator fixed, the timing gaps shrink** (equal-length overlay paths, seven rounds, paired against build A, difference of medians and permutation p): `shared_hit_medium` +1.4% (p = 0.05; 266.4 → 267.9 ns, +0.6%), `shared_publish_cycle` +1.6% (p = 0.04; 366.6 → 378.4 ns), `capture_array` +0.7% (p = 0.02), `shared_hit_small` −0.5%, `shared_miss` +0.1%, `find_exact_hit` −1.1% and `namespace_hit` −0.4%.

**Public shared-cache paths show no detectable difference.** The public benchmark `benchmarks/public_shared_cache.py` ran the actual release wheels with four workers and an isolated replica set, two rounds per build, equal-length overlay paths. Median latency per read in µs (median over the five builds per side, with range):

| Method / API / window   | `main` builds             | Candidate builds          | Difference         |    p |
| ----------------------- | ------------------------- | ------------------------- | ------------------ | ---: |
| find_one / async / cold | 534.932 (532.383–541.645) | 535.604 (533.173–542.701) | +0.672 µs (+0.1%)  | 0.60 |
| find_one / async / hot  | 8.856 (8.433–10.252)      | 8.816 (8.474–12.166)      | -0.040 µs (-0.5%)  | 0.78 |
| find_one / sync / cold  | 407.905 (406.171–412.353) | 405.195 (405.077–410.500) | -2.710 µs (-0.7%)  | 0.27 |
| find_one / sync / hot   | 10.180 (7.938–12.642)     | 8.517 (8.315–12.572)      | -1.663 µs (-16.3%) | 0.44 |
| identity / async / cold | 306.957 (302.924–310.048) | 304.393 (303.427–305.738) | -2.564 µs (-0.8%)  | 0.13 |
| identity / async / hot  | 6.166 (5.103–7.442)       | 7.421 (6.286–7.525)       | +1.255 µs (+20.4%) | 0.07 |
| identity / sync / cold  | 224.263 (222.788–225.097) | 222.927 (221.713–224.315) | -1.336 µs (-0.6%)  | 0.12 |
| identity / sync / hot   | 6.680 (5.768–6.898)       | 6.664 (5.574–7.002)       | -0.016 µs (-0.2%)  | 0.71 |

A hot read costs 6–10 µs, so a 9 ns native gap is 0.1%; a cold read, which includes the origin query and the owner's publication, costs 180–540 µs, so a 12 ns gap in publication is 0.003%.

The public warm hit of `small-entries` (CPU µs per read, ten builds, eight repetitions per build) shows no stable difference either. With overlay paths of unequal length the asynchronous hit was 2.2% slower (p = 0.02) and the synchronous one 0.2%; with equal-length paths the asynchronous hit was 0.5% slower (p = 0.98) and the synchronous one 0.9% slower (p = 0.01). The instructions per read are equal (asynchronous 78,498 against 78,425, synchronous 71,608 against 71,628) and the cycles differ by −0.1% asynchronously and +1.6% synchronously (p = 0.01), so the sign follows the API and the process layout rather than the code.

The remaining unexplained item is `shared_publish_cycle`: with the allocator fixed it takes 3.4% more cycles (55 cycles, about 13 ns) with no more instructions (+0.4%, p = 0.22), fewer branch misses and fewer L1D misses. The cause was not identified; the difference is invisible in a complete publication.

### Enabled admission cost

The next table isolates each limit between real requests: 40 processes per build with 4,096 distinct keys, all of which fit, so every build holds the same values. The cold phase admits every key; the repeat phase hits. Each cell is median CPU µs per read, with the paired change against the disabled candidate and its bootstrap interval in parentheses.

| API / phase    | Main                        | Other main build            | Disabled | Count only                  | Key only                    | Both                        |
| -------------- | --------------------------- | --------------------------- | -------- | --------------------------- | --------------------------- | --------------------------- |
| sync / cold    | 128.85 (-1.0 [-2.9, +1.1]%) | 129.99 (-0.6 [-2.0, +1.7]%) | 129.80   | 130.49 (-0.3 [-2.0, +0.8]%) | 133.33 (+3.2 [+1.4, +5.4]%) | 131.80 (+2.2 [+0.4, +3.6]%) |
| sync / repeat  | 6.24 (-0.3 [-0.6, +1.7]%)   | 6.24 (+0.3 [-0.4, +1.4]%)   | 6.26     | 6.25 (+0.7 [-0.4, +1.8]%)   | 6.26 (+0.7 [+0.0, +1.3]%)   | 6.27 (+0.9 [-0.2, +2.2]%)   |
| async / cold   | 222.78 (+0.1 [-1.7, +0.7]%) | 222.69 (-0.1 [-1.0, +1.0]%) | 222.22   | 223.66 (+0.5 [-0.4, +1.0]%) | 225.95 (+2.0 [+1.5, +3.5]%) | 227.20 (+1.9 [+0.3, +3.3]%) |
| async / repeat | 6.59 (-1.6 [-2.7, -0.2]%)   | 6.66 (-0.8 [-1.3, +0.5]%)   | 6.67     | 6.69 (-0.1 [-1.1, +1.3]%)   | 6.67 (-0.3 [-1.2, +0.9]%)   | 6.69 (+0.5 [-0.8, +1.3]%)   |

The count limit alone costs nothing measurable. Sizing the key alone costs 3.5 µs (sync) and 3.7 µs (async) per admitted miss, and both limits together 2.0 µs and 5.0 µs; the paired changes (+3.2% and +2.0%, then +2.2% and +1.9%) show that run-to-run noise is as large as the difference between the two configurations. Repeat reads agree with the disabled candidate within noise.

The in-process view shows where the key cost sits. Medians over nine rounds of one native admission or hit, with the paired change against no limit (bootstrap interval in brackets); "at capacity" admits into a full cache of 2,048 entries, so every admission also evicts.

| Workload                   | Disabled |                   Count only |                           Key only |                               Both |               Count at capacity |                   Both at capacity |
| -------------------------- | -------: | ---------------------------: | ---------------------------------: | ---------------------------------: | ------------------------------: | ---------------------------------: |
| `generic_miss_admission`   |   345 ns |  344 ns (-0.4% [-0.8, +1.8]) | 1234 ns (+257.5% [+255.3, +263.7]) | 1238 ns (+257.6% [+255.8, +262.9]) |     338 ns (-1.9% [-3.0, +1.8]) | 1240 ns (+259.1% [+252.0, +263.1]) |
| `identity_alias_admission` |  1661 ns | 1689 ns (+0.7% [-0.6, +2.6]) |    2870 ns (+72.6% [+71.9, +79.0]) |    2876 ns (+73.2% [+69.9, +75.2]) |    1582 ns (-4.6% [-6.6, -2.6]) |    2784 ns (+68.0% [+67.0, +71.7]) |
| `unique_key_admission`     |  4594 ns | 4587 ns (-1.3% [-2.6, +0.3]) |    6361 ns (+37.8% [+37.1, +39.9]) |    5873 ns (+27.1% [+26.4, +29.7]) | 4124 ns (-10.6% [-12.2, -10.3]) |    5915 ns (+28.6% [+27.4, +29.6]) |
| `generic_hit`              |   161 ns |  161 ns (-0.0% [-0.5, +0.4]) |        161 ns (+0.1% [-0.1, +0.5]) |        160 ns (-0.4% [-1.3, -0.1]) |     161 ns (+0.2% [-0.7, +1.1]) |        161 ns (-0.2% [-0.9, +0.6]) |
| `unique_key_hit`           |  2745 ns | 2741 ns (+0.5% [-1.4, +1.2]) |       2718 ns (-0.8% [-2.8, +1.2]) |       2766 ns (+1.2% [+0.6, +3.9]) |    2767 ns (+0.6% [-0.6, +2.9]) |       2781 ns (+0.7% [-1.0, +1.8]) |

Findings behind the optimization of the enabled path:

- **Count planning is free.** With the count limit alone, admissions cost as much as unrestricted ones, and an admission that evicts is faster than an unrestricted publication (−1.9% to −10.6%).
- **Key sizing dominates, and it is a floor.** The walk makes one `sys.getsizeof` call for each object of the canonical key that is not a tuple, and sizes tuples from a calibrated formula. It costs 0.9 µs for the generic key (about 20 objects), 1.2 µs for the identity key with its alias and 1.8 µs for the unique-key pair, which sizes two keys. Walking natively replaced a Python callback that cost 14–20 µs per admitted miss.
- **The end-to-end cost exceeds the in-process one** (2–5 µs against 0.9 µs) because the in-process loop revisits keys whose objects are in cache, while a real request walks objects last touched during the previous read. The in-process figure is the floor; the end-to-end figure is the cost to expect.
- **Hits are unchanged**, with one exception. A unique-key hit that resolves an alias and reads the identity costs 1.0–1.3% more (about 30 ns) when `max_entries` is set, because the facade then calls a separate native entry point, `lookup_identity_deferred`, for the deferred miss. An untrained copy of the plain lookup with an identical body was 57–68 ns slower than the original, and across the five candidate builds the deferred entry point's gap to the plain lookup ranges from 10 to 34 ns, so the cost follows the extra entry point rather than the deferral logic. Passing the deferral as a keyword to the shared entry point costs about 17 ns per call plus a per-call choice in the facade, within the separate entry point's own 10–34 ns range, so it offers no reliable gain. The end-to-end effect is about 0.4% of a 7.5 µs unique-key hit.
- **The rejected reductions are documented** in the [design record](../../openspec/changes/archive/2026-11-04-bound-process-local-key-overhead/design.md), including a hand-written hasher, inline containers, memoized subtree charges, native string sizes, batched `getsizeof` calls and unsafe pointer walking, each with its measurement or reason.

### Retained memory and pressure

At equal residency, enabling the limits changes no footprint. The candidate process starts 0.3 MiB larger than `main` (50.63 against 50.89 MiB of RSS before the first read), whether or not a limit is set, because its extension is 67 KiB larger (1,099,552 against 1,167,912 bytes) and the library imports more. The growth during the reads is the same. The table gives absolute MiB; RSS growth subtracts each child's own pre-read baseline, and the peak is the kernel's phase high-watermark during the repeated hit pass.

| API / build      | Cold RSS / USS / PSS  | Cold RSS growth (range) | Repeat peak RSS | Clear / close RSS |
| ---------------- | --------------------- | ----------------------- | --------------- | ----------------- |
| sync / main      | 53.12 / 34.35 / 40.43 | 2.48 (2.46–2.52)        | 53.76           | 53.03 / 53.29     |
| sync / disabled  | 53.37 / 34.61 / 40.69 | 2.48 (2.45–2.49)        | 54.01           | 53.27 / 53.13     |
| sync / count     | 53.42 / 34.61 / 40.68 | 2.47 (2.46–2.55)        | 54.06           | 53.32 / 52.63     |
| sync / key       | 53.37 / 34.61 / 40.69 | 2.47 (2.46–2.51)        | 54.01           | 53.27 / 53.19     |
| sync / enabled   | 53.37 / 34.61 / 41.15 | 2.48 (2.47–2.50)        | 54.06           | 53.26 / 52.59     |
| async / main     | 53.29 / 34.54 / 40.63 | 2.54 (2.52–2.57)        | 53.94           | 53.94 / 53.91     |
| async / disabled | 53.54 / 34.78 / 41.30 | 2.53 (2.52–2.57)        | 54.19           | 54.18 / 54.18     |
| async / count    | 53.53 / 34.78 / 41.31 | 2.53 (2.52–2.57)        | 54.18           | 54.16 / 54.16     |
| async / key      | 53.58 / 34.78 / 40.88 | 2.54 (2.52–2.56)        | 54.21           | 54.20 / 54.18     |
| async / enabled  | 53.60 / 34.79 / 41.33 | 2.54 (2.52–2.55)        | 54.24           | 54.21 / 54.21     |

Under pressure, `max_entries=4096` evicted 4,096 of 8,192 values, retained the newest 4,096-key suffix and served every suffix read from the cache. `max_key_bytes=2048` declined every 48-value key, retained nothing and delivered every result from the database; its repeated reads are database reads, not slower hits.

| API / pressure         | Values / charged BSON | Origin queries: cold / warm / repeat | Cold / repeat CPU                               | Declines |
| ---------------------- | --------------------- | ------------------------------------ | ----------------------------------------------- | -------: |
| sync / count-pressure  | 4096 / 299008 B       | 8192 / 0 / 0                         | 119.15 (112.04–131.14) / 6.10 (5.96–6.78)       |        0 |
| sync / key-pressure    | 0 / 0 B               | 8192 / 16384 / 16384                 | 152.39 (139.43–170.31) / 155.17 (146.96–176.61) |    40960 |
| async / count-pressure | 4096 / 299008 B       | 8192 / 0 / 0                         | 213.46 (201.71–228.16) / 6.56 (6.21–6.64)       |        0 |
| async / key-pressure   | 0 / 0 B               | 8192 / 16384 / 16384                 | 247.84 (236.11–263.66) / 247.17 (237.93–260.13) |    40960 |

### Memory protection on the issue #337 workload

The scenarios read 100,000 seeded documents (`{"_id": i, "code": "C%07d", "state": "active"}`, `code` indexed) through a cached `find_one` view in three phases: 64,000 distinct reads (cold), the same 64,000 again (warm) and 36,000 further distinct reads (evict). The BSON budget is 4 MiB, which holds 71,089 of the 59-byte results. The four scenarios cross the filter with the access order:

| Scenario         | Filter                                                            | Access order                                                  |
| ---------------- | ----------------------------------------------------------------- | ------------------------------------------------------------- |
| `small-entries`  | `{"code": ...}`                                                   | Sequential, each key once per phase                           |
| `large-keys`     | `{"code": ..., "state": {"$in": [48 values]}}`, built per request | Sequential                                                    |
| `skewed-entries` | `{"code": ...}`                                                   | 164,000 reads at log-uniformly distributed indexes (seed 337) |
| `skewed-keys`    | The 48-value filter                                               | The same skewed reads                                         |

The configurations are a plain PyMongo process (`direct`, the reference for Δ RSS), frozen `main`, the candidate with limits disabled, `max_entries=10000` (count), `max_key_bytes=2048` (key), both, and the deployment guide's example (`example`), `max_entries=50000` with `max_key_bytes=16384`. Δ RSS is the cached process's RSS minus the direct process's at the end of the last phase; the table gives the median and range of three repetitions of the synchronous API, and the asynchronous API agrees within 0.5 MiB with identical counts. The phase peak equals the end value in every row. "Warm hit rate" is the share of the 64,000 warm reads served from the cache.

`large-keys` reproduces the issue: 71,089 small results behind long filters hold 297 MiB of RSS above the plain driver, although only 4 MiB of BSON.

| Configuration | Δ RSS at end / peak, MiB    | Values + aliases | Charged BSON | Warm hit rate % | Origin queries: cold / warm / evict | Declines   |
| ------------- | --------------------------- | ---------------- | ------------ | --------------: | ----------------------------------- | ---------- |
| main          | 296.5 / 296.5 (296.5–296.6) | 71089 + 0        | 4194251 B    |           100.0 | 64000 / 0 / 36000                   | 0 / 0      |
| disabled      | 296.7 / 296.7 (296.7–296.9) | 71089 + 0        | 4194251 B    |           100.0 | 64000 / 0 / 36000                   | 0 / 0      |
| example       | 211.6 / 211.6 (211.6–211.7) | 50000 + 0        | 2950000 B    |             0.0 | 64000 / 64000 / 36000               | 0 / 0      |
| count         | 46.5 / 46.5 (46.4–46.5)     | 10000 + 0        | 590000 B     |             0.0 | 64000 / 64000 / 36000               | 0 / 0      |
| key           | 4.8 / 4.8 (4.6–4.8)         | 0 + 0            | 0 B          |             0.0 | 64000 / 64000 / 36000               | 164000 / 0 |
| both          | 4.7 / 4.7 (4.6–4.8)         | 0 + 0            | 0 B          |             0.0 | 64000 / 64000 / 36000               | 164000 / 0 |

`skewed-keys` is the same filter under a realistic access pattern:

| Configuration | Δ RSS at end / peak, MiB    | Values + aliases | Charged BSON | Warm hit rate % | Origin queries: cold / warm / evict | Declines   |
| ------------- | --------------------------- | ---------------- | ------------ | --------------: | ----------------------------------- | ---------- |
| main          | 146.5 / 146.5 (146.4–146.8) | 34746 + 0        | 2050014 B    |            82.5 | 18594 / 11177 / 4975                | 0 / 0      |
| disabled      | 146.9 / 146.9 (146.8–147.0) | 34746 + 0        | 2050014 B    |            82.5 | 18594 / 11177 / 4975                | 0 / 0      |
| example       | 146.9 / 146.9 (146.8–147.0) | 34746 + 0        | 2050014 B    |            82.5 | 18594 / 11177 / 4975                | 0 / 0      |
| count         | 46.1 / 46.1 (45.9–46.2)     | 10000 + 0        | 590000 B     |            72.2 | 20109 / 17771 / 9842                | 0 / 0      |
| key           | 4.7 / 4.7 (4.5–4.8)         | 0 + 0            | 0 B          |             0.0 | 64000 / 64000 / 36000               | 164000 / 0 |
| both          | 4.8 / 4.8 (4.5–4.8)         | 0 + 0            | 0 B          |             0.0 | 64000 / 64000 / 36000               | 164000 / 0 |

`skewed-entries` and `small-entries` use short filters, whose keys are small; the limits then trade hit rate for memory only through the entry count.

`skewed-entries`:

| Configuration | Δ RSS at end / peak, MiB | Values + aliases | Charged BSON | Warm hit rate % | Origin queries: cold / warm / evict | Declines |
| ------------- | ------------------------ | ---------------- | ------------ | --------------: | ----------------------------------- | -------- |
| main          | 24.5 / 24.5 (24.4–24.6)  | 34746 + 0        | 2050014 B    |            82.5 | 18594 / 11177 / 4975                | 0 / 0    |
| disabled      | 24.7 / 24.7 (24.7–24.8)  | 34746 + 0        | 2050014 B    |            82.5 | 18594 / 11177 / 4975                | 0 / 0    |
| example       | 24.8 / 24.8 (24.6–24.8)  | 34746 + 0        | 2050014 B    |            82.5 | 18594 / 11177 / 4975                | 0 / 0    |
| count         | 10.6 / 10.6 (10.5–10.6)  | 10000 + 0        | 590000 B     |            72.2 | 20109 / 17771 / 9842                | 0 / 0    |
| key           | 24.9 / 24.9 (24.7–24.9)  | 34746 + 0        | 2050014 B    |            82.5 | 18594 / 11177 / 4975                | 0 / 0    |
| both          | 10.5 / 10.5 (10.5–10.6)  | 10000 + 0        | 590000 B     |            72.2 | 20109 / 17771 / 9842                | 0 / 0    |

`small-entries`:

| Configuration | Δ RSS at end / peak, MiB | Values + aliases | Charged BSON | Warm hit rate % | Origin queries: cold / warm / evict | Declines |
| ------------- | ------------------------ | ---------------- | ------------ | --------------: | ----------------------------------- | -------- |
| main          | 45.6 / 45.6 (45.5–45.8)  | 71089 + 0        | 4194251 B    |           100.0 | 64000 / 0 / 36000                   | 0 / 0    |
| disabled      | 46.0 / 46.0 (45.9–46.0)  | 71089 + 0        | 4194251 B    |           100.0 | 64000 / 0 / 36000                   | 0 / 0    |
| example       | 35.1 / 35.2 (35.1–35.2)  | 50000 + 0        | 2950000 B    |             0.0 | 64000 / 64000 / 36000               | 0 / 0    |
| count         | 11.1 / 11.1 (11.0–11.1)  | 10000 + 0        | 590000 B     |             0.0 | 64000 / 64000 / 36000               | 0 / 0    |
| key           | 45.9 / 45.9 (45.9–46.0)  | 71089 + 0        | 4194251 B    |           100.0 | 64000 / 0 / 36000                   | 0 / 0    |
| both          | 11.0 / 11.0 (11.0–11.2)  | 10000 + 0        | 590000 B     |             0.0 | 64000 / 64000 / 36000               | 0 / 0    |

What the tables establish:

- **The entry count bounds memory in proportion to the entries kept.** 10,000 entries leave 46 MiB with long filters (−84% in `large-keys`, −69% in `skewed-keys`) and 11 MiB with short ones (−76% in `small-entries`, −57% in `skewed-entries`).
- **The key limit removes the long-filter entries entirely.** With 2,048 bytes, `large-keys` and `skewed-keys` retain nothing and decline 164,000 admissions; Δ RSS falls to 5 MiB. It does nothing for short keys (`key` equals `disabled` in the short-filter scenarios), because those keys already fit.
- **Coverage is the price.** The sequential scans cycle 64,000 keys through a smaller LRU, so no warm read hits: with 10,000 or 50,000 entries the warm hit rate falls from 100% to 0% and every warm read becomes a database query (64,000 more). Under the skewed pattern, 10,000 entries keep 72.2% of warm reads in the cache instead of 82.5%, at 17,771 instead of 11,177 warm queries. A key limit that declines every long filter returns all reads to the database (0% hits), as the declines show.
- **The deployment guide's example limits bound entries, not memory.** With long filters, 50,000 retained entries still cost 212 MiB; the right limits come from the key size of the application's own filters.

### Unique-key policy, alias churn and writes

The following occupancies are after cold admission and agree between sync and async and across repetitions. Main and the disabled candidate agree. Values and aliases are separate counts. BSON is charged once per resident value record; the unrestricted one-query case shares one encoded payload while charging two value records. Evictions and declines are counted within the cold phase.

| Cell         | Main / disabled values + aliases; BSON | Enabled values + aliases; BSON | Enabled cold evictions / declines |
| ------------ | -------------------------------------- | ------------------------------ | --------------------------------- |
| one-empty    | 2 + 1; 146 B                           | 1 + 0; 73 B                    | 0 / 1                             |
| pair-empty   | 2 + 1; 146 B                           | 1 + 1; 73 B                    | 0 / 0                             |
| half-prefill | 320 + 136; 23360 B                     | 128 + 0; 9344 B                | 56 / 57                           |
| full-prefill | 384 + 136; 28032 B                     | 128 + 0; 9344 B                | 120 / 121                         |
| many-to-one  | 129 + 128; 291411 B                    | 1 + 128; 2259 B                | 0 / 0                             |

Origin queries per phase, as main / disabled / enabled and identical in sync and async. The `warm + repeat` column sums the two warm phases.

| Cell         | cold            | warm + repeat | `_id`       | unrelated write | matched write   |
| ------------ | --------------- | ------------- | ----------- | --------------- | --------------- |
| one-empty    | 1 / 1 / 1       | 0 / 0 / 0     | 0 / 0 / 1   | 0 / 0 / 1       | 1 / 1 / 1       |
| pair-empty   | 1 / 1 / 1       | 0 / 0 / 0     | 0 / 0 / 0   | 0 / 0 / 0       | 1 / 1 / 1       |
| half-prefill | 128 / 128 / 128 | 0 / 0 / 71    | 0 / 0 / 128 | 0 / 0 / 128     | 1 / 1 / 128     |
| full-prefill | 128 / 128 / 128 | 0 / 0 / 7     | 0 / 0 / 128 | 0 / 0 / 128     | 1 / 1 / 128     |
| many-to-one  | 128 / 128 / 128 | 0 / 0 / 0     | 0 / 0 / 0   | 0 / 0 / 0       | 128 / 128 / 128 |

Process CPU per read of the repeat phase, median and range of ten processes, and the paired change of the disabled candidate against `main`:

| API / cell           | Main                | Other main build    | Disabled            | Enabled             | Disabled vs main % |
| -------------------- | ------------------- | ------------------- | ------------------- | ------------------- | ------------------ |
| sync / one-empty     | 7.58 (7.41–7.90)    | 7.51 (7.32–7.97)    | 7.41 (7.19–7.90)    | 7.88 (7.64–8.09)    | -1.9 [-4.3, +1.2]  |
| sync / pair-empty    | 7.54 (7.13–8.06)    | 7.51 (7.32–7.86)    | 7.50 (7.21–9.15)    | 7.44 (7.36–7.57)    | +0.0 [-2.2, +2.6]  |
| sync / half-prefill  | 7.61 (7.44–7.75)    | 7.48 (7.19–7.83)    | 7.37 (7.29–8.06)    | 7.87 (7.69–8.02)    | -2.1 [-3.5, -0.4]  |
| sync / full-prefill  | 7.69 (7.46–8.32)    | 7.48 (7.40–7.61)    | 7.46 (7.27–8.55)    | 7.92 (7.75–8.47)    | -3.3 [-4.8, +2.7]  |
| sync / many-to-one   | 11.31 (11.13–11.56) | 11.63 (11.22–15.07) | 11.34 (10.88–11.72) | 11.34 (11.09–11.63) | -0.7 [-2.0, +2.6]  |
| async / one-empty    | 7.97 (7.69–8.18)    | 7.91 (7.69–8.68)    | 7.96 (7.70–8.88)    | 8.33 (8.16–8.65)    | +2.4 [-1.8, +8.6]  |
| async / pair-empty   | 8.05 (7.76–8.35)    | 7.91 (7.71–12.88)   | 7.84 (7.80–12.77)   | 7.88 (7.72–8.18)    | -0.6 [-3.4, +1.3]  |
| async / half-prefill | 8.06 (7.72–8.17)    | 8.02 (7.79–8.79)    | 7.93 (7.81–8.13)    | 8.45 (8.23–8.94)    | -0.7 [-2.2, +1.3]  |
| async / full-prefill | 8.10 (7.93–8.69)    | 7.95 (7.78–8.24)    | 7.96 (7.80–8.70)    | 8.41 (8.17–9.21)    | -2.1 [-3.3, +1.2]  |
| async / many-to-one  | 12.24 (11.27–15.65) | 12.09 (11.77–15.87) | 11.99 (11.76–13.04) | 11.89 (11.66–12.51) | -2.4 [-3.5, +1.2]  |

Enabled reads cost the same as unrestricted ones where the repeat is served through the same path (pair-empty and many-to-one). Where the enabled cache holds values without aliases (one-empty and the prefilled cells), the repeat resolves no alias and falls back to the namespace entry, and costs 0.4–0.5 µs more per read.

With one slot, the subsequent `_id` phase needs one origin query and replaces the namespace value; the unrelated and matched write phases each need one. The two-slot pair has no origin query after the unrelated write and one after the matched write, just as the unrestricted control. The one-slot saving therefore trades identity reuse for original-query cacheability.

At half and full prefill the enabled cold pass ends with 128 values and no aliases. Capacity pressure reclaims aliases that earlier reads relied on, so the warm phases need 71 and 7 origin queries and each subsequent `_id`, unrelated-write and matched-write phase needs 128, versus 0 / 0 / 1 on both unrestricted builds. The extra CPU of those phases is the cost of 128 origin queries spread over 4,096 reads (about 120 µs each synchronously and 200 µs asynchronously), not admission overhead:

| API / cell / phase               | Main | Disabled | Enabled | Origin queries (main / enabled) |
| -------------------------------- | ---- | -------- | ------- | ------------------------------- |
| sync / half-prefill / identity   | 4.52 | 4.46     | 8.08    | 0 / 128                         |
| sync / half-prefill / unrelated  | 7.64 | 7.54     | 11.84   | 0 / 128                         |
| sync / half-prefill / matched    | 7.71 | 7.57     | 11.88   | 1 / 128                         |
| sync / full-prefill / identity   | 4.52 | 4.50     | 7.87    | 0 / 128                         |
| sync / full-prefill / unrelated  | 7.71 | 7.53     | 11.90   | 0 / 128                         |
| sync / full-prefill / matched    | 7.70 | 7.62     | 11.81   | 1 / 128                         |
| async / half-prefill / identity  | 4.93 | 4.89     | 11.10   | 0 / 128                         |
| async / half-prefill / unrelated | 8.02 | 7.91     | 15.22   | 0 / 128                         |
| async / half-prefill / matched   | 8.25 | 8.12     | 15.40   | 1 / 128                         |
| async / full-prefill / identity  | 4.93 | 4.82     | 11.58   | 0 / 128                         |
| async / full-prefill / unrelated | 7.98 | 7.92     | 15.50   | 0 / 128                         |
| async / full-prefill / matched   | 8.14 | 8.05     | 15.03   | 1 / 128                         |

This is the coverage cost of alias-first reclamation and namespace fallback. No additional unrelated value is evicted solely to obtain an alias.

For 128 aliases to one identity, the enabled policy retains one value and 128 aliases rather than 129 values and 128 aliases, reducing the BSON charge from 291,411 to 2,259 bytes. All builds make zero origin queries after an unrelated write and 128 after a matched write, and enabled CPU matches the other builds. The saving is removal of redundant namespace records and charges; alias-based reuse after unrelated writes already exists on `main`.

For alias churn, each cell summarizes thirty complete cycles: three cycles in each of ten fresh processes. Times are cumulative process CPU milliseconds for publishing all aliases and then individually removing all aliases. The capture stays held during removal. Every released checkpoint has zero values and charged BSON.

| Core / build         | 256 publish / remove ms             | 1,024 publish / remove ms              | 4,096 publish / remove ms                       |
| -------------------- | ----------------------------------- | -------------------------------------- | ----------------------------------------------- |
| reference / main     | 2.12 (2.06–2.50) / 0.50 (0.48–0.53) | 10.46 (10.26–14.00) / 4.21 (4.16–4.46) | 131.16 (129.32–145.84) / 116.97 (114.83–125.60) |
| reference / disabled | 2.03 (1.96–2.99) / 0.26 (0.25–0.35) | 7.83 (7.64–8.97) / 1.01 (0.96–1.20)    | 31.46 (30.52–34.42) / 4.01 (3.82–5.35)          |
| reference / enabled  | 4.00 (3.89–4.48) / 0.48 (0.46–0.55) | 15.88 (15.36–17.78) / 1.88 (1.82–2.18) | 63.19 (61.23–71.09) / 7.56 (7.35–10.71)         |
| native / main        | 0.52 (0.50–0.70) / 0.08 (0.08–0.13) | 2.03 (1.92–2.56) / 0.32 (0.30–0.41)    | 8.20 (7.84–9.76) / 1.26 (1.16–1.35)             |
| native / disabled    | 0.52 (0.50–0.83) / 0.08 (0.08–0.08) | 2.01 (1.95–2.29) / 0.29 (0.28–0.54)    | 8.14 (7.58–9.49) / 1.16 (1.13–1.50)             |
| native / enabled     | 0.52 (0.50–0.69) / 0.08 (0.08–0.17) | 2.02 (1.96–2.32) / 0.29 (0.28–0.33)    | 8.16 (7.82–11.43) / 1.16 (1.13–1.34)            |

The Python reference's 4,096-alias removal falls from 116.97 ms on `main` to 4.01 ms with limits disabled and 7.56 ms with them enabled, and its per-alias cost stays roughly constant as cardinality grows; it mutates one lazy set under the namespace lock rather than copying surviving membership. Native removal already scales linearly, and enabling the count limit leaves native publication and removal unchanged: the oldest-first alias order is threaded through the alias rows' unused namespace links rather than a separate map.

Complete admissions with 32,768 operations per thread across two namespaces, a 16 MiB BSON budget and a 131,072-record cap, so every build retains the same records without eviction:

| Core / build / threads   | CPU µs per operation |
| ------------------------ | -------------------- |
| reference / main / 1     | 8.44 (8.24–8.98)     |
| reference / disabled / 1 | 8.71 (8.55–9.10)     |
| reference / enabled / 1  | 13.62 (13.35–15.13)  |
| reference / main / 4     | 8.96 (8.83–9.38)     |
| reference / disabled / 4 | 9.21 (9.14–9.51)     |
| reference / enabled / 4  | 14.15 (14.00–14.59)  |
| native / main / 1        | 2.06 (2.03–2.31)     |
| native / disabled / 1    | 2.04 (2.01–2.07)     |
| native / enabled / 1     | 2.05 (2.02–2.78)     |
| native / main / 4        | 2.16 (2.10–2.23)     |
| native / disabled / 4    | 2.14 (2.11–2.26)     |
| native / enabled / 4     | 2.16 (2.09–2.45)     |

Native enabled admission costs 2.05 µs with one thread and 2.16 µs with four, against 2.04 and 2.14 µs disabled and 2.06 and 2.16 µs on `main`. The private Python reference's longer transaction (13.62 against 8.71 µs with one thread) documents the reference core's cost, not a public path.

### PGO training coverage

The instrumented build of the final source (`RUSTFLAGS=-Cprofile-generate`, trained by `scripts/pgo_training.py`) records which native functions the training reaches. Every new native path is reached. Training the opt-in workloads at a fifth of the default time (hit workloads at the full time) raises the profile total from 4.50 to 4.84 billion counts (+7.5%), and moves the hot threshold (the count covering 99% of the total) from 299,520 to 274,432 and the cold threshold (99.9%) from 58,368 to 55,296. The public end-to-end and guard cells are not training inputs; the native workloads of `compare` and `limits` share their data constructors with the training script, so they time trained code. Entry counts of the new paths:

| Native function                                         |      Training count |
| ------------------------------------------------------- | ------------------: |
| `Sizer::decide` (key walk; hottest block)               | 223,232 (7,786,011) |
| `key_decision`                                          |             428,544 |
| `retention_preflight`                                   |             222,208 |
| `value_plan` / `pair_fits`                              |        87,040 / 510 |
| `admit_unique_limited` (hottest block)                  |              93,184 |
| `AdmissionPlan::remove_value` / `remove_alias`          |          1,022 each |
| `identity_read` (hottest block)                         |           2,270,209 |
| `lookup_identity_deferred` and `resolve_alias` wrappers |        856,064 each |

The eviction path (`apply_plan`, hottest block 1,535) is rarely hot because it runs only at capacity. With the hit workload at a fifth of the time, the deferred lookup body ran 46,080 times, below the cold threshold, and was optimized for size.

### Test cost and reproduction

Five counterbalanced runs timed the same 1,331 pre-existing cases of the files listed below on `main` and on the candidate, and the 358 added cases separately. Selection matched collected node IDs after the budget-field rename and the cursor fixture's reordered parameter labels. Runs used one worker (`-n 0`), `--hypothesis-seed=337`, identical dependencies and the disposable-server setup, and the files `tests/core`, sync and async `test_unique_key_reads.py`, `test_cached_cursors.py`, `test_public_annotations.py`, `test_otel.py` and `test_pgo_training.py` (plus the new modules for the candidate). Times include process and fixture startup in the wall column.

| Selection                 | Main: wall s, median (range) | Candidate: wall s, median (range) | Main: test s        | Candidate: test s   |
| ------------------------- | ---------------------------- | --------------------------------- | ------------------- | ------------------- |
| Same 1,331 existing cases | 63.55 (62.63–82.20)          | 63.78 (62.38–64.29)               | 52.90 (52.00–54.52) | 53.14 (51.68–53.48) |
| 358 added cases           | —                            | 49.56 (49.10–50.01)               | —                   | 39.14 (38.61–39.42) |

The ranges overlap. Two earlier sets of five rounds on preceding revisions measured 63.06 against 63.07 and 61.84 against 62.70 seconds of wall time. The full Python coverage gate reached 100.00%, and the Rust unit tests and concurrency models passed. Native Rust coverage completion is tracked separately in [issue #328](https://github.com/alessio-locatelli/client-query-cache/issues/328), as the [native quality guide](../../docs/development/native-quality.md#native-coverage) explains.

To reproduce, build each tree with `just build`, then install each wheel into a separate target directory:

```bash
uv pip install --no-deps --target overlays/<label> dist/<wheel>.whl
```

Native workloads, with `control` an extra copy of build A's overlay:

```bash
uv run -- python -m research.native_build_profile.compare --overlay-root overlays --baseline baselineA --labels baselineB baselineC baselineD baselineE control candidate16 candidate17 candidate18 candidate19 candidate20 --rounds 5 --cpu 2 --workloads <the 25 workloads> --output micro.json
PYTHONPATH=overlays/candidate16:. PYTHONHASHSEED=0 setarch --addr-no-randomize taskset -c 2 uv run -- python -m research.native_build_profile.limits --rounds 9 --output limits.json
uv run -- python -m research.native_build_profile.end_to_end --overlay-root overlays --baseline baselineA --labels baselineB candidate16 candidate17 --output guard.json
```

The `<the 25 workloads>` are the names of `scripts/pgo_training.py`'s `WORKLOADS` that do not start with `limited_`; `main` has no limits to time. Public reads need the Podman socket and the contributor environment. This example seeds the nonunique workload and runs the enabled equal-residency cell; the build is selected by `PYTHONPATH`:

```bash
source scripts/testcontainers-bridge.sh
nice -n 19 taskset -c 2 python3 -c 'while True: pass' &
uv run --env-file=.env python - <<'PY'
import os
import subprocess
import sys
from pathlib import Path
from research.collection_adapter.live_error import fixture

root = Path.cwd()
site = Path('overlays/candidate16').resolve()
with fixture() as server:
    collection = server.process_memory.codes
    collection.insert_many(
        {'_id': i, 'code': f'C{i:07d}', 'state': 'active', 'revision': 0}
        for i in range(8194)
    )
    collection.create_index('code')
    host, port = server.address
    uri = f'mongodb://{host}:{port}/?directConnection=true'
    for api in ('sync', 'async'):
        subprocess.run(
            ['taskset', '-c', '2', sys.executable, '-m', 'research.process_memory.measure',
             'retention-child', uri, '--api', api, '--scenario', 'small-entries',
             '--distinct', '4096', '--retained', '4096', '--warm-repeats', '4',
             '--max-entries', '4096', '--max-key-bytes', '2048'],
            env=os.environ | {'PYTHONPATH': f'{site}:{root}', 'PYTHONHASHSEED': '337'},
            check=True,
        )
PY
kill %1
```

Run the other nonunique rows with their table parameters, choosing `--scenario large-keys` for the long-filter cells and `--distinct 8192 --retained 4096` for the pressure cells. Omit the limit arguments for the disabled control, `--max-entries` or `--max-key-bytes` alone for the per-limit cells, and add `--budget-field shared_budget_bytes` for `main`. Repeat ten (equal-residency per-limit: forty) times, reversing the build order on alternate repetitions, with stdout redirected to disposable JSONL files.

For the unique cells, replace the nonunique index with `collection.create_index('code', unique=True)` and add `--unique`. Set `(distinct, retained, max_entries, prefill, warm_repeats)` to `(1,1,1,0,4096)`, `(1,1,2,0,4096)`, `(128,128,128,48,32)` and `(128,128,128,112,32)` for the one-slot, pair, half-prefill and full-prefill cells. For many-to-one, insert document `_id=8194` with `code=[f'S{i:07d}' for i in range(128)]`, then use `(128,128,256,0,32)` plus `--single-identity`. Only the enabled build receives `--max-entries`; the harness supplies the `_id` and processed-write phases.

The core commands need no server. Run each for both cores and all three build configurations, ten repetitions each:

```bash
PYTHONPATH=overlays/candidate16:. PYTHONHASHSEED=337 uv run -- python -m research.process_memory.measure retention-core --core reference --scenario aliases --enabled
PYTHONPATH=overlays/candidate16:. PYTHONHASHSEED=337 uv run -- python -m research.process_memory.measure retention-core --core native --scenario contention --threads 4 --distinct 32768 --max-entries 131072 --budget 16777216 --enabled
```

Use `--core reference|native`, contention `--threads 1|4`, omit `--enabled` for disabled builds, and select `main`'s budget keyword as above. The issue #337 workload seeds 100,000 documents (`_id` and `code` as above, `code` indexed) into `process_memory.codes` and runs one child per scenario, API and configuration:

```bash
taskset -c 2 python -m research.process_memory.measure child <uri> large-keys sync direct
taskset -c 2 python -m research.process_memory.measure child <uri> large-keys sync cached --max-entries 10000
taskset -c 2 python -m research.process_memory.measure child <uri> large-keys sync cached --max-key-bytes 2048
```

Select the scenario (`small-entries`, `large-keys`, `skewed-entries`, `skewed-keys`) and API, and add `--budget-field shared_budget_bytes` for `main`. The PGO coverage check builds with `RUSTFLAGS=-Cprofile-generate=<directory>` through `maturin build --release --zig`, installs that wheel, runs `scripts/pgo_training.py` with `LLVM_PROFILE_FILE=<directory>/cov-%p.profraw`, merges with `llvm-profdata merge` and reads `llvm-profdata show --detailed-summary` and `--all-functions --counts`.

### Limitations of this section

- One host and one run order per run index. The end-to-end costs carry ±2–3% noise between independent builds of the same source, as the second `main` build shows; costs below that are not resolved.
- The key charge is shallow `sys.getsizeof` over the canonical key, not the memory of the retained objects. Δ RSS is the measured effect, and it depends on the allocator and the application's own filters.
- A cyclic scan larger than the entry limit never hits an LRU cache. The skewed rows show a realistic trade; the cyclic rows show the worst case.
- The `max_entries` unique-key hit carries the 30 ns described above, and `shared_publish_cycle` keeps a 13 ns difference whose cause is not identified ([details](#differences-on-unchanged-code)).
- glibc 2.43 and CPython's small-object allocator. Other allocators, glibc versions or Python versions can change retention.
