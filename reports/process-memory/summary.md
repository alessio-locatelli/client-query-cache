# Process memory beyond the cache budget

The October 10–11 sections preserve the historical measurements and names. See the [October 29 qualification](#retention-safeguards-qualification-on-2026-10-29) for the current optional retention limits and their measured costs.

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

## Retention safeguards qualification on 2026-10-29

This is checkpoint evidence for [issue #337](https://github.com/alessio-locatelli/client-query-cache/issues/337). Its measured performance regressions remain unaccepted. Further safeguard work is on hold until `migrate-remaining-hotpaths-to-rust` lands; resume with a new frozen baseline and a separate incremental comparison. The measurements below preserve the current cost and uncertainty, rather than qualifying a release. The measured wheel predates checkpoint lint cleanup and the subsequent MSRV-syntax and version-1 report-serialization corrections.

This section records measurements for issue [#337](https://github.com/alessio-locatelli/client-query-cache/issues/337). The preceding tables describe the October 10–11 implementation and retain its configuration names. The current capacity and sizing contracts are in the [API reference](../../docs/user/reference/api.md#optional-retention-limits).

### Builds and acquisition

Frozen `main` was `90007305e3c4dcb1adf20b46a1001faa13295ff8`. Both builds used release-mode Zig wheels, `client_query_cache-0.10.0-cp314-abi3-manylinux_2_28_x86_64.whl`, built with the same dependencies and linker:

```bash
CARGO_ZIGBUILD_PYTHON_PATH="$PWD/scripts/zig-linker.sh" uv run -- maturin build --release --zig --compatibility manylinux_2_28 --locked --out /tmp/agents/issue-337/wheels/current-candidate
```

The wheel SHA-256 values were `63976c67cb664c95dff474ad6e0d75f0132c97a25f8710cf78b83d7d9c245559` for frozen main and `1b1337c9f8b3017e4bbc2cef9ad1104c6cd4dc7723b7393eabedbd56a0ee67c2` for the candidate. Installed package files were compared with the wheel and candidate source. The recorded wheel fixes the measured implementation; the checkpoint status above identifies subsequent lint cleanup.

The environment was CPython 3.14.7, PyMongo 4.18.3, psutil 7.2.2, Rust 1.99.1, maturin 1.15.0, Linux 7.2.13 and glibc 2.43 in Fedora Toolbx on an Intel Core i3-13100 (eight logical CPUs). MongoDB was 9.0.4, from `mongo:9.0.4@sha256:dc28ed5a9d0fc616903c3f463bb1e53b92b49f441721b91926e87d90bf957ce8`. Final wheel acquisition completed in 277.2s. Long default controls completed in 56.9s. The additional six-pair generic control took 264.4 seconds; the combined final acquisition took 598.5 seconds, within the registered 30-minute bound.

Each measurement used a fresh Python process, the common candidate harness, one of those independently installed wheels, `PYTHONHASHSEED=337`, and a separate disposable MongoDB replica set. Three repetitions reversed build order on alternate repetitions. Startup, index discovery, change-stream readiness, and observation of write invalidations were outside measured read phases. CPU is whole-process CPU; latencies include the complete public call. Memory checkpoints collect garbage and report absolute RSS, USS, PSS and phase peak RSS. These child processes share the enclosing Toolbx cgroup, so its counters cannot establish per-child memory consumption and are excluded from the comparisons.

The BSON budget was 4 MiB and the per-value maximum 1 MiB. The nonunique workload stored 8,194 documents shaped as `{"_id": index, "code": "C0000000", "state": "active", "revision": 0}` with a `code` index. A one-field canonical key charged 1,491 bytes; the 48-value filter charged 4,947 bytes. The 2,048-byte threshold was frozen between those charges before candidate timing.

| Cell                             | Distinct / retained keys | Candidate limits                                                      | Measured phases                                       |
| -------------------------------- | -----------------------: | --------------------------------------------------------------------- | ----------------------------------------------------- |
| Disabled small and large filters |            8,192 / 4,096 | Both `None`                                                           | Cold; two retained-suffix passes of 16,384 reads each |
| Equal residency                  |            4,096 / 4,096 | `max_entries=4096`, `max_key_bytes=2048`, plus both disabled controls | Cold; two 16,384-read hit passes                      |
| Count pressure                   |            8,192 / 4,096 | `max_entries=4096`                                                    | Cold; two retained-suffix hit passes                  |
| Key pressure                     |            8,192 / 4,096 | `max_key_bytes=2048`                                                  | Cold; two repeated rejected-read passes               |

Both APIs also ran a unique-index stream: cold unique-key queries, repeated queries, `_id` reads, a processed unrelated write, and a processed matched-identity write. One- and two-slot controls used one distinct query; prefilled controls used 128 queries with eight preexisting aliases and 48 or 112 unrelated identity values, against a 128-record limit. A many-to-one control used 128 distinct aliases for one document, against 256 records. Each repeated phase contained 4,096 reads. Frozen main and the disabled candidate received the same requests with no record limit. The existing unrestricted policy already reuses identities through aliases after unrelated writes.

The core-only controls published and individually removed 256, 1,024 and 4,096 aliases for one identity, with a capture held, for three cycles per process. Enabled capacity was alias count plus two. Release and clear checkpoints checked reuse and teardown. Contention controls performed 32,768 complete capture/encode/admit operations per thread with one or four threads across two namespaces, a 16 MiB BSON budget and a 131,072-record cap, so all builds retained the same records without eviction. They measured the private Python reference core and the public native owner separately.

### Public read costs

Values below are medians, with minimum–maximum ranges in parentheses, across three independent processes per build and API. CPU and latency units are microseconds per read. `repeat` is the second retained-subset pass. Thousand reads/second is complete-phase throughput, including database waits on cold reads.

| API / filter / phase           | Main CPU               | Disabled CPU           | Main → disabled P50 / P95 / P99                     | Main → disabled thousand reads/s |
| ------------------------------ | ---------------------- | ---------------------- | --------------------------------------------------- | -------------------------------- |
| sync / small-entries / cold    | 113.45 (113.20–118.98) | 120.46 (112.32–121.85) | 131.62 / 232.84 / 397.75 → 137.66 / 271.75 / 412.76 | 6.51 → 6.01                      |
| sync / small-entries / repeat  | 8.62 (8.61–8.71)       | 9.41 (8.88–9.55)       | 8.49 / 8.99 / 11.92 → 8.85 / 14.25 / 15.44          | 115.73 → 106.03                  |
| sync / large-keys / cold       | 174.80 (169.28–177.00) | 169.83 (167.15–172.36) | 221.81 / 377.76 / 698.31 → 215.77 / 383.55 / 719.32 | 3.81 → 3.97                      |
| sync / large-keys / repeat     | 42.50 (42.28–42.65)    | 43.22 (42.57–45.26)    | 40.59 / 47.23 / 83.17 → 41.74 / 48.08 / 85.07       | 23.46 → 23.09                    |
| async / small-entries / cold   | 203.61 (202.68–203.68) | 210.71 (210.59–216.04) | 204.13 / 301.08 / 433.04 → 209.21 / 323.92 / 498.47 | 4.58 → 4.37                      |
| async / small-entries / repeat | 9.38 (9.33–9.45)       | 9.58 (9.24–10.36)      | 9.10 / 9.85 / 14.26 → 9.12 / 14.23 / 15.72          | 106.40 → 103.93                  |
| async / large-keys / cold      | 261.58 (257.56–264.87) | 267.35 (262.48–270.07) | 289.25 / 454.10 / 674.06 → 291.85 / 470.23 / 765.30 | 3.16 → 3.04                      |
| async / large-keys / repeat    | 42.78 (41.66–43.65)    | 42.82 (41.83–43.54)    | 41.32 / 46.60 / 82.08 → 41.58 / 45.87 / 82.92       | 23.32 → 23.31                    |

The equal-residency cell holds 4,096 identical values, no aliases and 299,008 charged BSON bytes on every build. It isolates the optional admission checks from changes in cache coverage.

| API / build / phase       | CPU (range)            | Wall time/read | P50 / P95 / P99          |
| ------------------------- | ---------------------- | -------------- | ------------------------ |
| sync / main / cold        | 115.18 (113.24–115.45) | 154.36         | 130.50 / 245.29 / 473.15 |
| sync / main / repeat      | 9.08 (8.74–9.24)       | 9.10           | 8.45 / 14.21 / 15.71     |
| sync / disabled / cold    | 112.97 (111.24–120.56) | 152.04         | 132.28 / 234.63 / 378.89 |
| sync / disabled / repeat  | 9.21 (9.06–9.40)       | 9.23           | 8.72 / 13.71 / 15.27     |
| sync / enabled / cold     | 128.13 (126.23–129.67) | 165.84         | 149.43 / 245.15 / 388.07 |
| sync / enabled / repeat   | 9.28 (8.91–9.29)       | 9.30           | 8.78 / 13.86 / 15.20     |
| async / main / cold       | 206.96 (203.84–209.43) | 224.66         | 205.28 / 310.47 / 485.63 |
| async / main / repeat     | 9.38 (8.98–9.51)       | 9.52           | 9.02 / 11.06 / 15.64     |
| async / disabled / cold   | 207.46 (201.97–210.05) | 226.06         | 206.65 / 301.35 / 437.17 |
| async / disabled / repeat | 9.73 (9.23–9.78)       | 9.76           | 9.12 / 14.72 / 16.14     |
| async / enabled / cold    | 227.14 (221.48–230.10) | 247.96         | 224.01 / 361.94 / 550.71 |
| async / enabled / repeat  | 9.30 (9.13–9.44)       | 9.32           | 9.04 / 9.90 / 14.43      |

Both limits add a miss-only shallow key walk and capacity planning. Compared with the disabled candidate, equal-residency cold CPU increased from 112.97 to 128.13 µs synchronously and 207.46 to 227.14 µs asynchronously. Warm medians were 9.21 → 9.28 µs and 9.73 → 9.30 µs. These measurements establish an enabled admission cost; they do not establish a warm-hit speedup. The one-slot namespace fallback also has a longer query-hit path than an unrestricted identity/alias hit, quantified below.

### Retained memory and pressure

The following table gives absolute MiB at equal residency. Growth subtracts each child’s own pre-read baseline. RSS, USS and PSS are medians; the RSS growth range is shown to expose allocator sensitivity. The peak is the kernel phase high-watermark during the repeated hit pass. Clear and close release all resident records and charged BSON; RSS can remain mapped for allocator reuse.

| API / build      | Cold RSS / USS / PSS  | Cold RSS growth (range) | Repeat peak RSS | Clear / close RSS |
| ---------------- | --------------------- | ----------------------- | --------------- | ----------------- |
| sync / main      | 56.80 / 38.48 / 46.42 | 1.95 (1.94–1.95)        | 57.07           | 57.00 / 57.00     |
| sync / disabled  | 54.97 / 36.68 / 44.60 | 2.72 (2.72–2.72)        | 55.63           | 54.71 / 55.03     |
| sync / enabled   | 54.99 / 36.68 / 44.62 | 2.73 (2.72–2.73)        | 55.66           | 54.74 / 55.06     |
| async / main     | 56.96 / 38.56 / 46.49 | 1.96 (1.96–1.97)        | 57.25           | 57.25 / 57.26     |
| async / disabled | 55.06 / 36.71 / 44.64 | 2.73 (2.72–2.73)        | 55.79           | 54.91 / 55.17     |
| async / enabled  | 55.11 / 36.77 / 44.70 | 2.74 (2.73–2.76)        | 55.82           | 55.14 / 55.40     |

At equal residency, enabling the limits produces little footprint difference at this scale. The absolute and baseline-subtracted values above are whole-process observations, not evidence that each entry became larger or smaller. An exploratory prebuilt-key diagnostic using `tracemalloc` and glibc `mallinfo2` found essentially equal live native allocation growth (1,404,384 bytes on main; 1,402,592 on the candidate), while initially available free heap differed by about 1 MiB. Growth alone therefore cannot attribute a per-entry cost. That exploratory diagnostic supports an attribution boundary; the tables above use the final release wheels.

| API / pressure         | Values / charged BSON | Origin queries: cold / warm / repeat | Cold / repeat CPU (ranges)                      | Repeat RSS / USS / PSS MiB |
| ---------------------- | --------------------- | ------------------------------------ | ----------------------------------------------- | -------------------------- |
| sync / count-pressure  | 4096 / 299008 B       | 8192 / 0 / 0                         | 116.54 (116.22–123.78) / 8.71 (8.56–9.04)       | 55.77 / 37.38 / 45.31      |
| sync / key-pressure    | 0 / 0 B               | 8192 / 4096 / 4096                   | 180.74 (176.54–180.82) / 180.18 (180.15–181.84) | 53.24 / 34.89 / 42.83      |
| async / count-pressure | 4096 / 299008 B       | 8192 / 0 / 0                         | 206.46 (205.38–214.50) / 9.57 (9.20–9.76)       | 55.81 / 37.49 / 45.41      |
| async / key-pressure   | 0 / 0 B               | 8192 / 4096 / 4096                   | 278.51 (277.76–281.07) / 273.03 (272.66–284.09) | 53.31 / 35.00 / 42.94      |

Count pressure evicted 4,096 values, retained the known 4,096-key suffix and made every measured suffix read a hit. The unrestricted controls retained 8,192 values and charged 598,016 bytes. Key pressure retained no values, recorded 8,192 cold declines and 4,096 more per repeated pass, and delivered every native result. Its repeated reads are database reads, rather than slower cache hits. The approximately 30 MiB difference from the large-filter control comes from rejecting those keys, not from storing them more efficiently.

### Unique-key policy, alias churn and writes

The following occupancies are after cold admission and agree between sync and async. Main and the disabled candidate agree. Values and aliases are separate counts. BSON is charged once per resident value record; the unrestricted one-query case shares one encoded payload while charging two value records.

| Cell         | Main / disabled values + aliases; BSON | Enabled values + aliases; BSON | Enabled cold evictions / declines |
| ------------ | -------------------------------------- | ------------------------------ | --------------------------------- |
| one-empty    | 2 + 1; 146 B                           | 1 + 0; 73 B                    | 0 / 1                             |
| pair-empty   | 2 + 1; 146 B                           | 1 + 1; 73 B                    | 0 / 0                             |
| half-prefill | 320 + 136; 23360 B                     | 128 + 0; 9344 B                | 56 / 57                           |
| full-prefill | 384 + 136; 28032 B                     | 128 + 0; 9344 B                | 120 / 121                         |
| many-to-one  | 129 + 128; 291411 B                    | 1 + 128; 2259 B                | 0 / 0                             |

| API / cell           | Main repeat CPU (range) | Disabled repeat CPU (range) | Enabled repeat CPU (range) | Enabled repeat P50 / P95 / P99 |
| -------------------- | ----------------------- | --------------------------- | -------------------------- | ------------------------------ |
| sync / one-empty     | 11.63 (11.40–11.86)     | 13.17 (11.65–13.36)         | 13.28 (12.89–13.43)        | 12.94 / 13.87 / 16.63          |
| sync / pair-empty    | 12.14 (11.08–13.27)     | 11.79 (11.67–13.62)         | 11.88 (11.83–13.81)        | 11.66 / 12.27 / 17.15          |
| sync / half-prefill  | 13.07 (11.71–13.63)     | 11.91 (11.83–13.13)         | 13.09 (12.96–13.30)        | 12.84 / 13.75 / 15.30          |
| sync / full-prefill  | 12.62 (11.73–13.80)     | 12.23 (12.19–13.67)         | 13.09 (13.04–14.22)        | 12.84 / 13.62 / 19.56          |
| sync / many-to-one   | 15.75 (15.50–16.16)     | 17.08 (15.43–17.25)         | 15.74 (15.62–17.18)        | 15.44 / 16.63 / 23.32          |
| async / one-empty    | 12.29 (12.20–13.49)     | 12.35 (12.27–14.06)         | 15.35 (13.64–16.01)        | 13.45 / 23.45 / 25.59          |
| async / pair-empty   | 12.50 (12.07–13.90)     | 14.00 (13.86–14.12)         | 12.13 (12.06–12.37)        | 12.00 / 12.67 / 14.09          |
| async / half-prefill | 12.39 (12.34–12.50)     | 12.56 (12.26–12.59)         | 14.45 (13.92–16.24)        | 13.75 / 22.34 / 24.06          |
| async / full-prefill | 12.73 (12.31–14.14)     | 12.52 (12.42–14.42)         | 13.62 (13.60–15.80)        | 13.50 / 14.21 / 16.27          |
| async / many-to-one  | 16.58 (16.40–16.91)     | 16.30 (16.18–16.30)         | 16.44 (16.26–17.54)        | 15.98 / 18.55 / 27.68          |

Every repeated unique-query phase hit without origin traffic. With one slot, the subsequent `_id` phase needs one origin query and replaces the namespace value; the unrelated and matched-write query phases each need one origin query. The two-slot pair has no origin query after the unrelated write and one after the matched write, just as the unrestricted control. The one-slot saving therefore trades identity reuse for original-query cacheability.

At half/full prefill, the enabled cold pass ends with 128 namespace values and no aliases. Each subsequent `_id`, unrelated-write and matched-write phase needs 128 origin queries, versus 0 / 0 / 1 on both unrestricted builds. The unrelated-write phase costs 17.10 / 17.32 µs per read synchronously and 20.47 / 20.36 µs asynchronously, versus 12.00 / 12.27 and 12.33 / 12.44 on the disabled candidate. This is the coverage cost of alias-first reclamation and namespace fallback. No additional unrelated value is evicted solely to obtain an alias.

For 128 aliases to one identity, the enabled policy retains one value and 128 aliases rather than 129 values and 128 aliases, reducing the BSON charge from 291,411 to 2,259 bytes. All builds make zero origin queries after an unrelated write and 128 after a matched write. Enabled repeated-query CPU is 15.74 µs (sync) and 16.44 µs (async), versus 17.08 and 16.30 with limits disabled. The saving is removal of redundant namespace records and charges; alias-based reuse after unrelated writes already exists on main.

### Alias membership and transaction contention

For alias churn, each cell below summarizes nine complete cycles: three cycles in each of three fresh processes. Times are cumulative process CPU milliseconds for publishing all aliases and then individually removing all aliases. The capture stays held during removal. Keys have fixed-size hashing costs.

| Core / build         | 256 publish / remove ms             | 1,024 publish / remove ms              | 4,096 publish / remove ms                       |
| -------------------- | ----------------------------------- | -------------------------------------- | ----------------------------------------------- |
| reference / main     | 2.17 (2.07–3.00) / 0.50 (0.47–0.84) | 10.61 (10.09–12.49) / 4.19 (4.14–4.30) | 129.42 (126.72–131.89) / 117.03 (112.11–120.39) |
| reference / disabled | 2.01 (1.96–2.65) / 0.27 (0.25–0.49) | 7.84 (7.60–9.12) / 1.02 (0.97–1.05)    | 31.34 (30.54–36.53) / 3.96 (3.79–7.48)          |
| reference / enabled  | 4.18 (3.96–5.35) / 0.48 (0.47–0.50) | 16.54 (15.69–18.95) / 1.86 (1.80–2.89) | 65.88 (64.57–73.48) / 7.47 (7.41–8.19)          |
| native / main        | 0.60 (0.57–0.62) / 0.09 (0.08–0.09) | 2.29 (2.24–4.29) / 0.32 (0.31–0.34)    | 9.48 (9.17–15.33) / 1.28 (1.27–1.31)            |
| native / disabled    | 0.61 (0.58–0.64) / 0.09 (0.08–0.09) | 2.41 (2.31–2.45) / 0.32 (0.30–0.33)    | 9.67 (9.34–12.81) / 1.26 (1.20–1.33)            |
| native / enabled     | 0.64 (0.61–1.12) / 0.09 (0.09–0.10) | 2.47 (2.38–2.53) / 0.37 (0.33–0.37)    | 10.12 (9.59–10.56) / 1.48 (1.40–2.76)           |

The Python reference’s 4,096-alias removal falls from 117.03 ms to 3.96 ms with limits disabled and 7.47 ms with limits enabled. Its new per-alias cost stays roughly constant as cardinality grows; the implementation mutates one lazy set under the namespace lock rather than copying surviving membership. Native removal already scales linearly. Every released checkpoint has zero values and charged BSON; candidate snapshots also have zero aliases. The three cycles reuse capacity. The benchmark keeps its input alias list through each cycle. RSS and GC object checkpoints measure retained storage, not total transient allocation volume; timing plus the in-place membership operation establish removal of cumulative set copying.

| Core / build / threads   | CPU/read µs (range) | Wall/read µs (range) | P50 / P95 / P99 µs     |
| ------------------------ | ------------------- | -------------------- | ---------------------- |
| reference / main / 1     | 9.19 (9.12–9.48)    | 9.23 (9.14–9.50)     | 8.50 / 11.48 / 15.47   |
| reference / main / 4     | 14.41 (14.38–16.81) | 14.40 (14.37–16.79)  | 9.30 / 36.79 / 76.48   |
| reference / disabled / 1 | 9.20 (9.06–9.32)    | 9.22 (9.09–9.34)     | 8.45 / 12.24 / 15.56   |
| reference / disabled / 4 | 14.21 (14.15–14.23) | 14.20 (14.18–14.24)  | 9.33 / 31.95 / 76.34   |
| reference / enabled / 1  | 15.23 (14.88–15.43) | 15.28 (14.93–15.46)  | 14.41 / 17.72 / 25.15  |
| reference / enabled / 4  | 26.02 (25.61–26.19) | 25.98 (25.57–26.15)  | 15.99 / 63.92 / 150.02 |
| native / main / 1        | 3.15 (2.79–3.15)    | 3.16 (2.80–3.16)     | 2.48 / 4.67 / 6.07     |
| native / main / 4        | 4.12 (3.93–4.37)    | 4.12 (3.93–4.37)     | 2.65 / 8.12 / 18.18    |
| native / disabled / 1    | 2.88 (2.85–2.97)    | 2.88 (2.86–2.99)     | 2.53 / 3.52 / 5.26     |
| native / disabled / 4    | 3.98 (3.60–4.16)    | 3.99 (3.60–4.15)     | 2.66 / 6.74 / 16.73    |
| native / enabled / 1     | 2.99 (2.83–3.12)    | 3.00 (2.84–3.13)     | 2.50 / 4.53 / 5.88     |
| native / enabled / 4     | 4.05 (3.13–4.74)    | 4.05 (3.13–4.73)     | 2.89 / 7.58 / 13.72    |

All contention cells retained exactly 32,768 or 131,072 values without eviction. Native enabled admission costs 2.99 µs with one thread versus 2.88 µs disabled; four-thread CPU medians are 4.05 versus 3.98 µs. The private Python reference’s longer transaction costs 15.23 versus 9.20 µs with one thread and 26.02 versus 14.21 µs with four. The exported `CacheCore` and both public managers use the native owner; the reference result documents its transaction cost rather than a public fallback path.

### Disabled hit-path investigation

Short controls varied between similar cells. A separate six-pair acquisition extended the generic controls to 65,536 reads per warm phase; their paired changes had mixed signs. The unique-key controls were then extended to 32,768 reads per phase. A ten-pair direct-call comparison found a median saving of about 0.015 µs by omitting the unused keyword in disabled facades. A six-pair public comparison also favored reusing the existing constant-false native identity lookup path synchronously, so both improvements are retained. The asynchronous changes overlapped run variation.

The final short small-filter hit cell showed a 9% median CPU increase. To check its duration sensitivity, the same final wheels ran six counterbalanced pairs with 65,536 reads per warm phase. The longer control confirms a smaller synchronous hit cost; cold and asynchronous paired changes are less consistent. The table reports CPU µs/read and the median paired percentage change, with ranges.

| API / filter / phase          | Main CPU                  | Disabled CPU              | Paired change %       |
| ----------------------------- | ------------------------- | ------------------------- | --------------------- |
| sync / matched-long / cold    | 117.618 (114.511–128.630) | 115.543 (111.798–118.736) | -2.741 (-7.692–2.984) |
| sync / matched-long / repeat  | 8.928 (8.851–9.065)       | 9.141 (9.061–9.285)       | 2.427 (0.766–4.712)   |
| sync / large-long / cold      | 169.207 (165.286–179.740) | 175.442 (163.932–177.667) | 0.700 (-1.995–6.366)  |
| sync / large-long / repeat    | 43.185 (42.199–43.435)    | 43.444 (43.263–43.525)    | 0.547 (0.209–2.976)   |
| async / matched-long / cold   | 213.950 (208.598–218.508) | 205.381 (204.316–219.241) | -3.300 (-5.844–4.097) |
| async / matched-long / repeat | 9.373 (9.155–9.843)       | 9.424 (9.298–9.774)       | 1.178 (-4.751–2.411)  |
| async / large-long / cold     | 268.981 (263.269–278.473) | 268.520 (258.595–271.650) | -0.863 (-4.054–3.170) |
| async / large-long / repeat   | 42.995 (42.103–43.467)    | 43.442 (42.660–44.559)    | 0.848 (-0.664–3.517)  |

The final six-pair control below uses the final wheel. It reports CPU µs/read as median (minimum–maximum); unlike the short three-repetition cells, this exposes the remaining small default-path cost.

| API / phase       | Main                   | Disabled candidate     |
| ----------------- | ---------------------- | ---------------------- |
| sync / repeat     | 11.956 (11.625–12.207) | 12.359 (12.095–12.953) |
| sync / identity   | 5.432 (5.207–5.496)    | 5.474 (5.245–5.630)    |
| sync / unrelated  | 11.941 (11.752–12.503) | 12.090 (11.903–12.334) |
| sync / matched    | 12.012 (11.651–12.434) | 12.357 (12.145–12.438) |
| async / repeat    | 12.516 (12.442–13.234) | 12.724 (12.393–13.020) |
| async / identity  | 5.725 (5.377–6.099)    | 5.760 (5.685–5.843)    |
| async / unrelated | 12.726 (12.521–13.536) | 12.672 (12.527–12.781) |
| async / matched   | 12.830 (12.410–13.542) | 12.705 (12.492–13.186) |

The remaining few tenths of a microsecond are a measured regression, with the strongest repeatability in the synchronous hit paths. Its exact source has not been isolated further. The tests establish that sizing is absent when limits are disabled and on warm hits; that invariant alone does not prove zero hit-path cost. The enabled key walk also has the cold-admission cost shown above. The safeguards therefore trade CPU and, under pressure, cache coverage for bounded retained records and key charges. No disabled-path speedup is claimed.

### Test cost and reproduction

Three counterbalanced runs timed the same 1,239 pre-existing cases in `tests/core`, sync/async `test_unique_key_reads.py`, `test_cached_cursors.py`, `test_public_annotations.py` and `test_otel.py`. Selection matched collected node IDs after the budget-field rename, the default observer parameter and the cursor fixture’s reordered parameter labels. The 308 additional cases, including the three new test modules, were timed separately. Runs used one worker (`-n 0`) to remove scheduling differences, `--hypothesis-seed=337`, identical dependencies and the same disposable-server setup. Times include process and fixture startup. This timing campaign preceded the two final hit-path micro-optimizations. Its recorded corpus excludes the twelve retained-report compatibility cases added afterward.

| Selection                 | Main seconds, median (range) | Candidate seconds, median (range) |
| ------------------------- | ---------------------------- | --------------------------------- |
| Same 1,239 existing cases | 63.26 (61.55–63.76)          | 62.65 (61.70–63.26)               |
| 308 added cases           | —                            | 25.82 (25.77–26.22)               |

The existing-case ranges overlap. The full Python coverage gate reached 100.00% with no incorrectly excluded lines. The final release wheel passed 1,539 affected core/read cases. The timed corpus additionally includes eight cases from `tests/benchmark/test_process_memory.py`, giving its total of 1,547. Rust unit tests and concurrency models also passed. Native Rust coverage completion is tracked separately in [issue #328](https://github.com/alessio-locatelli/client-query-cache/issues/328), as the [native quality guide](../../docs/development/native-quality.md#native-coverage) explains. Completed tests and resource acquisitions emitted no failures or warnings.

Raw outputs are disposable files under `/tmp/agents/issue-337/`: `current/` contains the final three-repetition wheel campaign, `current-refined/` contains the six-pair unique-key hit controls, `current-generic/` contains the six-pair generic controls, and `test-duration/` contains node selection and timing logs. Earlier controls and optimization experiments are retained beside them. The common harness’s completion record is required before accepting any child’s output; its tests reject missing or inconsistent completion records.

To reproduce, build the current wheel with the command above and frozen main from a detached checkout, using the same interpreter and release flags. Install each wheel into a separate target directory with `uv pip install --no-deps --target <site> <wheel>`. Use the [contributor environment](../../CONTRIBUTING.md) and the repository’s disposable replica-set fixture. This example seeds the exact nonunique workload and runs the enabled equal-residency cell:

```bash
source scripts/testcontainers-bridge.sh
uv run --env-file=.env python - <<'PY'
import os
import subprocess
import sys
from pathlib import Path
from research.collection_adapter.live_error import fixture

root = Path.cwd()
site = Path('/tmp/agents/issue-337/sites/current-candidate')
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
            [sys.executable, '-m', 'research.process_memory.measure',
             'retention-child', uri, '--api', api, '--scenario', 'small-entries',
             '--distinct', '4096', '--retained', '4096', '--warm-repeats', '4',
             '--max-entries', '4096', '--max-key-bytes', '2048'],
            env=os.environ | {'PYTHONPATH': f'{site}:{root}', 'PYTHONHASHSEED': '337'},
            check=True,
        )
PY
```

Run the other nonunique rows with their table parameters, choosing `--scenario large-keys` for the long-filter cells. Omit both limit arguments for the disabled control. Select the frozen main site and add `--budget-field shared_budget_bytes` for main. Repeat three times, reversing the three-build order on alternate repetitions. Redirect stdout to disposable JSONL files and stderr to separate logs.

For the unique cells, replace the nonunique index with `collection.create_index('code', unique=True)` and add `--unique`. Set `(distinct, retained, max_entries, prefill, warm_repeats)` to `(1,1,1,0,4096)`, `(1,1,2,0,4096)`, `(128,128,128,48,32)` and `(128,128,128,112,32)` for the one-slot, pair, half-prefill and full-prefill cells. For many-to-one, insert document `_id=8194` with `code=[f'S{i:07d}' for i in range(128)]`, then use `(128,128,256,0,32)` plus `--single-identity`. Only the enabled build receives `--max-entries`; the harness supplies the `_id` and processed-write phases.

The core commands require no server. Run each for both cores and all three build configurations with the same target-site selection, `PYTHONHASHSEED=337` and three counterbalanced repetitions:

```bash
PYTHONPATH=/tmp/agents/issue-337/sites/current-candidate:. PYTHONHASHSEED=337 uv run -- python -m research.process_memory.measure retention-core --core reference --scenario aliases --enabled
PYTHONPATH=/tmp/agents/issue-337/sites/current-candidate:. PYTHONHASHSEED=337 uv run -- python -m research.process_memory.measure retention-core --core native --scenario contention --threads 4 --distinct 32768 --max-entries 131072 --budget 16777216 --enabled
```

Use `--core reference|native`, contention `--threads 1|4`, omit `--enabled` for disabled builds, and select main’s budget keyword as above. The alias command runs all three cardinalities and capture/cleanup cycles internally. For test timings, collect the listed paths with `pytest --collect-only -q -n 0`, match the existing nodes using the normalization described above, then time those nodes and the remaining candidate nodes separately with `--hypothesis-seed=337 -n 0`.

For the longer final default-hit controls, use the unique one-query setup with `--warm-repeats 32768`, both limits omitted and six counterbalanced repetitions of main and candidate. The exploratory long generic controls use `--warm-repeats 16` with the equal-residency and large-filter setups.
