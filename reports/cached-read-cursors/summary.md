# Cached read cursor measurements

Measured on 2026-10-05 with Python 3.14.6, PyMongo 4.18.2, MongoDB 8.0.4 (`mongo:8.0.4-noble`) in the existing disposable replica-set fixture, Linux 7.2.8 / glibc 2.43, and an Intel Core i3-13100. The client and container run on the same host.

Run:

```bash
just pytest -- -n 0 -s -m benchmark tests/benchmark/test_cached_read_cursors.py --log-level=WARNING --log-file-level=WARNING
```

The benchmark performs ten repetitions per phase, using identical sorted documents and `next()` followed by complete `to_list()` consumption for native, cold, and warm reads. Timing starts before cursor construction, so aggregation command time is included. Cold repetitions clear the namespace; each admitting warm case verifies ten cache hits, zero origin commands, and exact results. Early-close reads consume one document and close. Explicit batch size 7 is a native bypass control. Latency measurements run without allocation tracing or profiling; separate executions measure allocations and profile one cold read. Raw output remains untracked.

These are medians from one sequential local run, without randomized phase order or confidence intervals. Server and background-stream scheduling affect comparisons, particularly first-document latency; a cold median below native is not evidence that capturing documents accelerates origin execution.

## Complete consumption

Total latency includes cursor construction, the first document, and draining the remaining documents. Throughput is documents divided by median warm latency.

| API / method    | Documents × payload bytes | Native ms | Cold ms | Hit ms | Hit documents/s |
| --------------- | ------------------------: | --------: | ------: | -----: | --------------: |
| sync find       |                   10 × 64 |     1.136 |   0.752 |  0.085 |         117,509 |
| sync find       |                 240 × 128 |     2.561 |   1.437 |  0.182 |       1,317,234 |
| sync find       |                240 × 4096 |     3.316 |   2.917 |  0.281 |         853,789 |
| sync find       |               4000 × 1024 |     6.811 |  17.757 |  2.741 |       1,459,481 |
| sync aggregate  |                   10 × 64 |     1.130 |   1.184 |  0.082 |         121,359 |
| sync aggregate  |                 240 × 128 |     2.766 |   1.589 |  0.172 |       1,391,304 |
| sync aggregate  |                240 × 4096 |     1.361 |   2.685 |  0.277 |         866,426 |
| sync aggregate  |               4000 × 1024 |     7.380 |  17.894 |  2.742 |       1,459,002 |
| async find      |                   10 × 64 |     1.181 |   1.052 |  0.088 |         113,766 |
| async find      |                 240 × 128 |     0.805 |   1.759 |  0.183 |       1,312,910 |
| async find      |                240 × 4096 |     2.367 |   2.484 |  0.307 |         780,488 |
| async find      |               4000 × 1024 |     7.215 |  18.081 |  2.703 |       1,479,947 |
| async aggregate |                   10 × 64 |     1.750 |   0.835 |  0.084 |         118,765 |
| async aggregate |                 240 × 128 |     3.686 |   1.885 |  0.180 |       1,330,377 |
| async aggregate |                240 × 4096 |     2.387 |   2.597 |  0.285 |         840,630 |
| async aggregate |               4000 × 1024 |     7.290 |  18.355 |  2.764 |       1,447,283 |

Every natural 10-document read issued one query and no getMore. Natural 240- and 4,000-document reads issued one query and one getMore. Hits issued neither. Explicit size-7 bypasses issued one query and respectively 1, 34, and 571 getMore commands; they retained no candidate and produced no hits. The existing stream-cost benchmark consumers now consume cursors during activation, correctness checks, warmup, and timing; their workload sizes and thresholds are unchanged.

For 240 documents with 4,096-byte payloads:

| API / method    | Native first µs | Cold first µs | Hit first µs | Early-close total µs |
| --------------- | --------------: | ------------: | -----------: | -------------------: |
| sync find       |          1637.1 |         956.0 |        204.8 |                963.9 |
| sync aggregate  |           704.4 |        1090.4 |        198.3 |               1029.3 |
| async find      |          1181.4 |         982.2 |        222.1 |                960.4 |
| async aggregate |          1187.1 |        1029.0 |        204.9 |               1089.6 |

All early-close runs issued one query and zero getMore commands. Multi-batch cursors required one killCursors; already completed server cursors required none. This confirms that native first batches are buffered but remaining batches are fetched only when consumed. Later command-cursor `batch_size()` behavior is covered separately by differential tests; the invocation bypass control does not claim to measure that path.

## Allocation peaks and admission bounds

Peaks below are incremental Python heap bytes reported by `tracemalloc` from before construction through complete materialization, including native document buffers, snapshot wrappers, final encoding, stored values, and the returned list allocated in that execution. The pre-existing fixture documents and previously warmed cache are outside each measurement. Native/C-extension or server allocations invisible to tracemalloc and process RSS are not measured. Stream tasks can add noise. This is an observed heap peak, not a total-process memory guarantee.

| API / method    | Documents × payload | Native heap MiB | Cold heap MiB | Hit heap MiB | Retained snapshot bytes |
| --------------- | ------------------: | --------------: | ------------: | -----------: | ----------------------: |
| sync find       |          240 × 4096 |           1.636 |         3.086 |        1.078 |               1,000,080 |
| sync find       |         4000 × 1024 |          10.706 |        15.306 |        6.637 |               4,380,000 |
| sync aggregate  |          240 × 4096 |           1.635 |         3.085 |        1.077 |               1,000,080 |
| sync aggregate  |         4000 × 1024 |          10.705 |        15.304 |        6.635 |               4,380,000 |
| async find      |          240 × 4096 |           1.643 |         3.089 |        1.080 |               1,000,080 |
| async find      |         4000 × 1024 |          10.708 |        15.309 |        6.639 |               4,380,000 |
| async aggregate |          240 × 4096 |           1.642 |         3.088 |        1.078 |               1,000,080 |
| async aggregate |         4000 × 1024 |          10.707 |        15.307 |        6.636 |               4,380,000 |

The retained encoded snapshot payload was 1,000,080 bytes for 240 × 4,096 under a 1 MiB limit and 4,380,000 bytes for 4,000 × 1,024 under an 8 MiB limit. Every append checks its bound. Peak Python heap is substantially larger: the entry limit bounds encoded payload, not native batches, wrappers, consumer retention, or transient finalization.

With a 32 KiB capture limit and 240 × 4,096, all four API/method combinations rejected the candidate after retaining at most 29,169 bytes, continued returning all documents, and admitted nothing. At a 135-byte entry limit, the one-document snapshot fits exactly but the 143-byte final stored list does not; all four combinations retained at most 135 bytes and rejected final admission. No warm phase is reported for these rejected candidates.

Eight concurrent cursors each consumed 50 of 240 × 4,096 documents. Their retained payload total was 1,666,800 bytes; observed heap peaks ranged from 4,250,301 to 4,294,218 bytes. After closing all eight cursors, traced current heap ranged from 55,639 to 77,951 bytes. After tracing stops, a GC inventory verifies that their collector objects have been reclaimed while the closed cursors remain reachable. The residual includes live closed cursor objects and surrounding test/driver state; it is not retained candidate payload. For 4,000 × 1,024, the same prefix retained 438,000 bytes across eight cursors. Ten-document controls finish within the 50-document prefix and therefore have no partial candidate.

Separate lifetime regressions verify that complete exhaustion, explicit close, and context exit reclaim collectors while sync/async find and aggregate cursor objects remain reachable. Snapshot payload is released on rejection, and the benchmark verifies collector reclamation after closing partial cursors rather than relying only on cleared capture fields. Fault and cancellation regressions verify no admission, empty buffers, and native cleanup when a later batch fails or an async getMore await is cancelled. Generation, availability, and manager-close regressions verify that rejected candidates still deliver documents and started hits retain their own isolated snapshot.

## CPU profile

In the synchronous find 4,000 × 1,024 cold profile, 4,001 BSON `_dict_to_bson` calls consumed about 6 ms of internal time, capture `append` about 4 ms, 8,000 raw-document wrapper constructions about 4 ms, raw-document inflation about 3 ms, and socket receives about 3 ms. These profiled times are instrumentation-dependent and are separate from the latency table. Encoding and raw-document handling are measured CPU costs; server wait also matters. The implementation snapshots each delivered document once and finalizes through the existing value admission path. No custom serializer or encoded-publication optimization is proposed: any further optimization must preserve custom codecs, document classes, sizing, and generation guards and demonstrate a benefit against this baseline.

## Driver checks

The differential cursor and session suite is also run using the minimum supported driver:

```bash
source scripts/testcontainers-bridge.sh
env -u UV_LOCKED uv run --quiet --isolated --with pymongo==4.18.1 --group docs -- pytest -n 0 -q tests/test_cached_cursors.py tests/test_bound_sessions.py --log-level=WARNING --log-file-level=WARNING
```

The protected integration hooks and native/local cursor contract are documented in [the architecture guide](../../docs/development/architecture.md).
