# Native internals results

This report records the evidence and per-component dispositions for the [migrate-remaining-hotpaths-to-rust](../../openspec/changes/migrate-remaining-hotpaths-to-rust/design.md) change. Builds, commands, and resource scope are registered in [plan.md](plan.md). Paths are relative to `src/client_query_cache/` unless prefixed otherwise.

## Starting evidence

The assessment table in design.md cites the historical evidence available before this change: the [ordinary-wheel adoption](../native-process-local-cache/results.md#ordinary-wheel-adoption) of the native local owner, the [cursor capture profile](../cached-read-cursors/summary.md#cpu-profile), the [shared current-cost attribution](../shared-worker-cache/current-costs/results.md#attribution-and-alternatives) with its [native encoding](../shared-worker-cache/current-costs/rust-encoding.md), and the [rejected native selection trials](../shared-worker-cache/current-costs/native-trials.md#registered-sync-identity-controls). None of them is a matched observation of a candidate against M; each candidate below has its own short benchmark.

## Development preflight

M passed the registered preflight in 74.8 seconds of the 300-second deadline, including four replica-set lifecycles. Every cell used the installed M wheel and extension (`4ef9fa15…`).

| Cell                                                           | Wall seconds | Observations                                                                                                                                                                                    |
| -------------------------------------------------------------- | -----------: | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `find`, 16 × 128-byte documents, independent/shared, cold/hot  |         21.4 | Every cold window missed 128 reads and every hot window hit 128; all 128 cold keys per window hit on the follow-up read without origin reads. Shared cold admissions travelled over the socket. |
| `identity`, shared cold (D4 queue check)                       |         15.0 | All 128 admissions per model were queued natively, processed by the owner, and admitted; 144 entries stayed resident with no rejection or eviction, and every key then hit.                     |
| `aggregate`, 128 × 1,024-byte documents, cold                  |         17.5 | Both paths admitted and then hit every cold key.                                                                                                                                                |
| `find_one_in`, 256-element `$in`, independent/shared, cold/hot |         21.0 | Every origin `find` carried the complete registered predicate; outcomes matched the `find` cells.                                                                                               |

Hot shared windows of this size leave the owner's CPU below 100 clock quanta; the collector records that as unresolved instead of a zero cost. Acquisition components reject unresolved CPU outside profiled windows.

Two earlier attempts are rejected and retained under `/tmp/agents/native-internals/`. The first stopped at the owner CPU resolution assertion for a hot shared window (`M-preflight-rejected-cpu-resolution`). The second ran a 256 × 1,024-byte aggregate whose 144 shared entries exceed the collector's fixed 32 MiB owner budget: the drain check reported 120 of 144 resident entries after eviction (`M-preflight-rejected-shared-eviction`). The registered spot check uses 128 documents instead.

## Capture

The capture candidate (`e4a4f0de`) passed the preflight in 75.7 seconds. Its benchmark ran three counterbalanced blocks against M from harness `602e910b` in 197 seconds, with every window validated and every CPU component resolved. Each block's acquisition verified the registered wheel, the installed package files and the native core.

| Cell (four workers)                                                      | Model | Paired change per block (M → capture) | Median |
| ------------------------------------------------------------------------ | ----- | ------------------------------------- | -----: |
| Target: cold `find`, 4,000 × 1,024-byte documents, CPU per complete read | sync  | −25.6%, −25.4%, −23.5%                | −25.4% |
|                                                                          | async | −20.2%, −21.1%, −27.7%                | −21.1% |
| Target P50 latency                                                       | sync  | −21.4%, −19.9%, −17.4%                | −19.9% |
|                                                                          | async | −14.6%, −18.3%, −23.8%                | −18.3% |
| Target P99 latency                                                       | sync  | −51.3%, −48.2%, −41.8%                | −48.2% |
|                                                                          | async | −39.2%, −42.2%, −55.8%                | −42.2% |
| Target worker PSS after the window                                       | both  | −3.5% to −3.7%                        |  −3.6% |
| Control: hot `find`, 16 × 128-byte documents, CPU per read               | sync  | −3.0%, +5.5%, −3.4%                   |  −3.0% |
|                                                                          | async | +10.5%, −2.6%, +7.6%                  |  +7.6% |

M's target used 18.3–19.8 ms of CPU per complete read; the candidate used 13.7–14.8 ms. Peak RSS stayed within 0.2%. Every target window admitted all 128 results within the 8 MiB entry limit and hit every key on the follow-up read.

The control's directions are mixed and its spread within one build (M: 42.1–48.9 µs async, 44.1–49.6 µs sync) exceeds the paired changes. Its hits never construct a capture, so it executes no changed code; its P50 latency stayed within 1%. It is recorded as noise, not a regression.

Bounded profiles (32 reads per worker in block 0 of each build) attribute the saving to `CursorCapture.append`, whose cumulative time per 4,000-document read fell from 22.0 ms to 9.2 ms: the per-document slice and `RawBSONDocument` construction (6.8 ms) and the second encoding pass over the wrapper list disappeared. The remaining capture cost is PyMongo's per-document encoding (6.5 ms), native appends (1.1 ms) and the final envelope copy (1.5 ms). The profiles measure elapsed time with instrumentation and do not qualify retention.

**Disposition: retained.** The registered target improves in all six paired observations, and no control or resource observation shows an adverse effect. The changelog records the large-result `find()` miss improvement.

## Candidate map

| Component                   | Current code path                                                                                                                                                                                                                                                                                   | Candidate and control                   | Disposition |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- | ----------- |
| Capture                     | `CursorCapture.append` encodes each document inside an envelope, slices the embedded bytes into a new object, and wraps them in `RawBSONDocument`; `finish` passes the wrapper list to `admit_namespace`, which encodes the whole list again; the native owner then retains that bytes object.      | `capture` cells in `CANDIDATES`         | Retained    |
| Key preparation             | Native lookups call the Python `canonicalize` operation for every discriminator and `order_sensitive_key` followed by `canonicalize` for identities; facade classification (`read_classification.py`, `read_validation.py`, `query_filters.py`) traverses the same filters before key construction. | `preparation` cells                     | Pending     |
| Shared residency            | `SharedCacheOwner` constructs the Python `CacheCore` with `IndexPublisher` and `ArenaPayloads`; `_drain_rings` touches the private `_lru`, and `_admit_local` holds `progress._lock` and `CacheCore._availability_lock` across validation and admission.                                            | `owner` cells                           | Pending     |
| Shared frames and dispatch  | `_frames` decodes each socket frame in Python; `select-*` requests decode keys through `decode_key` and `KeyCache.decode`; queued admissions use `decode_queued_frame`.                                                                                                                             | Attributed inside the `owner` benchmark | Pending     |
| Event interpretation        | `_core/stream_events.py` routes each change event and `_core/stream_cost.py` records telemetry.                                                                                                                                                                                                     | Conditional on task 5.1                 | Pending     |
| Facade dispatch             | Sync/async `collection.py` and `cursors.py` bind sessions, classify requests, and call the core.                                                                                                                                                                                                    | Conditional on task 5.1                 | Pending     |
| Metadata, lifecycle, others | Collection/index/namespace metadata caches, health/backoff, stream supervision, configuration, snapshots, errors, OpenTelemetry, public wrappers.                                                                                                                                                   | Conditional on task 5.1                 | Pending     |
