# Process memory beyond the cache budget

Measured on 2026-10-10 and 2026-10-11 with CPython 3.14.7 (pymalloc), PyMongo 4.18.2, psutil 7.2.2, and MongoDB 8.0.4 (`mongo:8.0.4-noble`, single-member replica set), on Linux 7.2.9 with an AMD Ryzen 3 210 (8 logical CPUs) and rootless Podman. Measured processes ran with glibc 2.39 from the Ubuntu 24.04 user space of the `mongo:8.0.4-noble` image.

`shared_budget_bytes` and `max_entry_bytes` bound stored and captured BSON. This report measures how much process memory a cache-enabled application uses beyond the same reads without the cache, and classifies each cost. It complements the [Memray churn tier](../../docs/development/memory-regression-tests.md), the [cursor allocation report](../cached-read-cursors/summary.md), the [filter normalization report](../query-filter-normalization/summary.md), and the group PSS figures of the [shared worker cache study](../../docs/development/research/shared-worker-cache-feasibility.md); it does not repeat their allocation measurements.

## Reproduce

Use the [contributor environment](../../CONTRIBUTING.md) with the Podman socket enabled:

```bash
source scripts/testcontainers-bridge.sh
uv run -- python -m research.process_memory.measure run --runs 5 --output benchmark-reports/process-memory/final.json
uv run -- python -m research.process_memory.measure summarize benchmark-reports/process-memory/final.json
```

`--scenarios` selects a subset. A full run takes about two hours; raw JSON stays in the ignored `benchmark-reports/` directory. The pre-fix baseline ran the same harness, without the `cycles` scenario, from a disposable worktree of `893c636`, whose `src/` is identical to the parent of the fix.

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
| `small-entries`, cold           |     3.6 MiB |  64,001 | 72.2 (71.9–72.3)                              | 1,148–1,150 B    |                 19.5 |
| `small-entries`, after eviction |     4.0 MiB |  71,089 | 86.5 (86.2–86.6)                              | 1,244–1,245 B    |                 21.1 |
| `large-keys`, cold              |     3.6 MiB |  64,001 | 326.6 (326.5–326.9)                           | 5,317–5,318 B    |                 90.1 |
| `large-keys`, after eviction    |     4.0 MiB |  71,089 | 369.1 (369.0–369.4)                           | 5,413–5,414 B    |                 91.8 |

Container `memory.current` differences match the RSS differences within 1.2 MiB in every row, and `anon` and USS differences within 0.4 MiB. Absolute container memory followed USS and stayed about 17 MiB below RSS, which also counts the interpreter's and libraries' shared file pages. Phase peaks equal the end-of-phase values except during eviction of small entries, which peaked 1.9 MiB (`small-entries`) and 3.6 MiB (`large-keys`) above the result.

Warm passes added 0.6 MiB for `documents` and 2.2 MiB for the small-entry scenarios, without new entries: hits decode each result into new objects that the reads then discard. `result-sets` warm passes added nothing.

When the application kept 16 decoded results (about 14.9 MiB of BSON), RSS grew by 19.5 MiB in direct processes and by 17.5 MiB in cached ones: the application owns that memory in both modes.

### Open cursors

Thirty-two cursors that each read 220 of 224 documents retained 30,765,770 bytes of captured payload (29.3 MiB). Δ RSS was 34.1 MiB (33.8–34.2) synchronously and 30.6 MiB (30.1–33.2) with asyncio. Closing the cursors left 18.6 MiB (sync) and 30.0 MiB (async) above direct processes; `malloc_trim(0)` then reduced both to about 4.7 MiB.

### Memory after closing

| Scenario        | Δ RSS after closing, sync | Δ RSS after closing, async | After `malloc_trim(0)`, sync / async |
| --------------- | ------------------------: | -------------------------: | -----------------------------------: |
| `documents`     |          19.5 (10.4–19.7) |              7.4 (6.4–7.6) |                            7.7 / 7.6 |
| `result-sets`   |           13.2 (2.5–22.5) |            −0.4 (−4.6–0.7) |                           1.3 / −1.9 |
| `small-entries` |          23.2 (22.2–24.2) |           37.1 (30.9–40.3) |                          23.4 / 37.3 |
| `large-keys`    |          34.0 (31.5–48.7) |           56.9 (50.3–65.4) |                          34.2 / 57.1 |

Each value includes the library's modules, which stay imported after closing. GC-tracked object counts after closing were 34–145 below each process's cached baseline, so no cache objects survived. glibc trimming returns the memory that held stored BSON and captures, which glibc allocates outside Python's small-object allocator. It cannot return memory held by Python's small-object arenas, which stay mapped while any block in them is live; keys, entries, and bookkeeping are small objects, so retention grows with the number of entries rather than with stored bytes.

In `cycles`, five managers in one process each filled a 1 MiB budget with 17,772 small entries and evicted 22,229:

| Cycle | Δ RSS filled, sync / async | Δ RSS closed, sync / async | GC objects after closing, sync / async |
| ----: | -------------------------: | -------------------------: | -------------------------------------: |
|     1 |                23.1 / 22.9 |                15.1 / 16.0 |                        46,019 / 46,222 |
|     2 |                24.0 / 24.0 |                14.6 / 18.6 |                        46,019 / 46,262 |
|     3 |                24.0 / 24.1 |                16.3 / 19.5 |                        46,019 / 46,302 |
|     4 |                24.0 / 24.1 |                15.8 / 19.5 |                        46,019 / 46,328 |
|     5 |                24.0 / 24.4 |                16.8 / 19.9 |                        46,019 / 46,246 |

Filled peaks grew by at most 0.4 MiB after the first cycle and object counts stayed flat, so closed managers release their cache and later managers reuse the retained memory. An exploratory in-process run of 12 cycles of 64,000 small entries on the pre-fix code showed the same plateau, with 19.2 MB in allocated small-object blocks after the last close against 36.5 MB in unused pools of partly used arenas.

### Effect of the bookkeeping fix

The pre-fix baseline repeated every scenario except `cycles`. Its cached processes started about 1.5 MiB higher, most likely because the fresh read-only worktree had no compiled bytecode for the library, unlike the main checkout; growth per entry cancels that difference.

| Scenario                        | Growth per entry, before → after | Growth ÷ stored BSON, before → after | GC objects per entry, before → after |
| ------------------------------- | -------------------------------: | -----------------------------------: | -----------------------------------: |
| `documents`, after eviction     |                  5,139 → 4,928 B |                          1.18 → 1.13 |                                5 → 3 |
| `small-entries`, after eviction |                  1,313 → 1,245 B |                          22.3 → 21.1 |                              12 → 11 |
| `large-keys`, after eviction    |                  5,483 → 5,414 B |                          92.9 → 91.8 |                              23 → 22 |

`result-sets` and `partial-cursors` did not change beyond noise.

### Per-entry attribution

`tracemalloc` attribution of 5,000 `_id` entries and 20,000 generic `find_one` entries, admitted after warm-up through the synchronous view, records requested bytes rather than RSS:

| Retained per entry after the fix                   | `_id`, 4.4 KB documents | One-field filter | 48-value `$in` filter |
| -------------------------------------------------- | ----------------------: | ---------------: | --------------------: |
| Stored BSON `bytes` object                         |                   4,403 |               92 |                    92 |
| Canonical query key tuples                         |                       – |  648 (10 tuples) |     1,784 (22 tuples) |
| Identity or filter values                          |                      31 |               49 |                 2,679 |
| Entry, key object, generation guard, LRU and index |               about 310 |        about 290 |             about 290 |
| Identity state and its index                       |               about 125 |                – |                     – |
| Total, including smaller items                     |                   4,896 |            1,078 |                 4,893 |

The identity value is decoded by the library; filter strings are the objects the application passed in each request.

Before the fix, each `_id` entry also retained a 216-byte empty alias set and a 72-byte `NamespaceId`, and each generic entry the 72-byte `NamespaceId`.

## Classification

- **Expected object ownership.** Stored BSON lives in Python `bytes` objects with a 33-byte header. Hits decode results into new Python objects, as direct PyMongo reads do, and the application owns any result it keeps. Allocator rounding and size classes add a few percent.
- **Justified trade-offs.** About 0.3 KB per entry for the entry, its key object, its generation guard, and the LRU and reclamation indexes, plus about 0.1 KB of identity state for `_id` entries; this supports exact invalidation, eviction, and namespace reclamation without scanning. Cursor captures keep encoded snapshots plus wrappers, 34.1 MiB of RSS for 29.3 MiB of payload, and release them when a cursor closes.
- **Avoidable duplication.** The empty alias set and the per-entry `NamespaceId` were removed by this change. Canonical keys still wrap each order-sensitive node in an extra tuple layer, about half of the key tuples in the attribution above; [issue #245](https://github.com/alessio-locatelli/client-query-cache/issues/245) tracks removing it, because it changes every namespace key.
- **Leaks or missing cleanup.** None found. Closing cursors and managers released every cache object, repeated cycles reached a stable peak, and `malloc_trim(0)` recovered the glibc share of freed memory.
- **Capacity considerations.** The BSON budget does not bound memory for small entries or large filters: a 4 MiB budget of 59-byte results cost 86.5 MiB, and 369.1 MiB with a 48-value `$in` filter. Open miss cursors add up to their payload plus wrappers. Freed memory stays in the process for reuse, so RSS follows the peak. The [deployment guide](../../docs/user/operations/deployment.md#memory-beyond-the-cache-budget) summarizes these points for users.

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
