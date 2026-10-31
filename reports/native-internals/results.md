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

## Preparation

The preparation candidate (`9b15985b`) passed the preflight in 75.1 seconds. Its benchmark ran three counterbalanced blocks against the retained capture build from harness `e7b88888` in 144 seconds, with every window validated and every CPU component resolved.

| Cell (four workers)                                                          | Model | Paired change per block (capture → preparation) | Median |
| ---------------------------------------------------------------------------- | ----- | ----------------------------------------------- | -----: |
| Target: hot `find_one`, 256-element `$in`, 1,024 resident keys, CPU per read | sync  | −60.5%, −55.2%, −62.6%                          | −60.5% |
|                                                                              | async | −52.1%, −54.7%, −47.5%                          | −52.1% |
| Target P50 latency                                                           | sync  | −60.0%, −59.5%, −60.2%                          | −60.0% |
|                                                                              | async | −58.3%, −58.0%, −56.4%                          | −58.0% |
| Control: hot identity, independent, CPU per read                             | sync  | −34.1%, +7.3%, −2.0%                            |  −2.0% |
|                                                                              | async | +39.0%, +23.7%, +1.6%                           | +23.7% |
| Control: hot identity, shared, worker plus owner CPU per read                | sync  | +4.0%, +2.5%, −3.0%                             |  +2.5% |
|                                                                              | async | +24.0%, +39.6%, −2.4%                           | +24.0% |

The target fell from 54.4–61.3 µs to 22.3–30.5 µs of CPU per read. Worker PSS stayed within 0.6%. Peak worker RSS, which includes warmup, moved between −5.0% and +5.1% across all cells without a consistent direction (target: −0.2% to +3.1%).

The identity controls cost 5.8–9.8 µs per read and their windows are bimodal within a single build: the capture build's own P50 latency alternated between about 5 µs and 9 µs. The async controls' positive medians are therefore a specific adverse signal that three short pairs cannot resolve. A narrowly affected recheck alternated the two installed builds four times with 16,384 reads per worker:

| Recheck cell              | Model | Capture CPU per read (µs) | Preparation CPU per read (µs) | P50 latency (µs), capture → preparation |
| ------------------------- | ----- | ------------------------- | ----------------------------- | --------------------------------------- |
| Hot identity, independent | sync  | 5.79, 6.34, 6.37, 6.68    | 6.45, 5.61, 6.64, 6.00        | 5.12–5.17 → 4.89–4.98                   |
|                           | async | 7.25, 6.46, 6.65, 8.55    | 6.26, 6.89, 7.91, 6.55        | 5.78–5.94 → 5.56–5.67                   |
| Hot identity, shared      | sync  | 7.69, 6.79, 6.42, 7.81    | 7.03, 5.89, 5.78, 5.63        | 4.71–7.43 → 4.41–4.67                   |
|                           | async | 6.25, 6.18, 7.28, 5.99    | 7.14, 6.16, 5.88, 6.35        | 5.10–5.20 → 4.99–5.04                   |

Every candidate P50 is at or below the corresponding capture range, and the CPU distributions overlap. The recheck finds no regression; the short-run control signal is attributed to window noise.

Bounded profiles (256 reads per worker in block 0) attribute the target saving to key preparation. The capture build spent 99.9 µs in `_order_sensitive_key`, 85.7 µs in `canonicalize` and 102.8 µs in `_contains_unsafe_construct` per instrumented read; the candidate spent 14.8 µs in three native `discriminator` calls and 3.2 µs in the native filter scan. The candidate still performs 13 abstract-base-class checks per read for the codec fingerprint inside each read shape; task 5.1 assesses that repeated work.

**Disposition: retained.** The registered target improves in all six paired observations, and the recheck resolves the adverse control signal. The changelog records the large-filter `find_one()` improvement.

## Shared owner

The owner candidate (`29106b20`) passed the preflight in 74.5 seconds, including the queued identity check. Its benchmark ran three counterbalanced blocks against the retained preparation build from harness `57c8d52f` in 140 seconds. Every target window drained exactly 4,096 queued admissions, all admitted, with 5,120 resident entries, no rejection or eviction and every follow-up read a hit; drains completed within one 10 ms observation poll in both builds. Every CPU component was resolved.

| Cell (four workers, shared)                                   | Model | Paired change per block (preparation → owner) | Median |
| ------------------------------------------------------------- | ----- | --------------------------------------------- | -----: |
| Target: cold identity, drained admissions, owner CPU per read | sync  | −47.7%, −46.0%, −42.5%                        | −46.0% |
|                                                               | async | −46.2%, −44.9%, −47.5%                        | −46.2% |
| Target: worker plus owner plus supervision CPU per read       | sync  | −12.7%, −9.8%, −4.4%                          |  −9.8% |
|                                                               | async | −8.3%, −8.0%, −9.2%                           |  −8.3% |
| Target worker CPU per read                                    | sync  | −5.5%, −2.4%, +3.6%                           |  −2.4% |
|                                                               | async | −2.8%, −2.6%, −3.4%                           |  −2.8% |
| Target foreground P50 latency                                 | sync  | −5.7%, −3.3%, +4.9%                           |  −3.3% |
|                                                               | async | −3.9%, −3.7%, −4.5%                           |  −3.9% |
| Target owner PSS                                              | both  | −1.6% to −2.4%                                |  −1.9% |
| Control: hot identity, group CPU per read                     | sync  | −8.0%, +8.6%, −8.2%                           |  −8.0% |
|                                                               | async | −18.8%, +4.6%, −1.9%                          |  −1.9% |
| Control P50 latency                                           | sync  | −1.7%, +1.3%, −3.9%                           |  −1.7% |
|                                                               | async | −1.2%, +1.9%, +0.2%                           |  +0.2% |

Owner CPU per drained cold read fell from 38.4–44.9 µs to 20.7–24.2 µs and group CPU from 224–345 µs to 202–316 µs. Worker PSS stayed within 0.5%. The synchronous target's P95/P99 tails moved in both directions (P99: −38.1%, +5.4%, +60.0%), as did the controls' tails; the medians and the asynchronous tails improved. With no consistent adverse direction, the tail variation is recorded as noise.

The profiled windows inside the benchmark were too short for an external sampler to attach, so a separate attribution run repeated 256 cold reads per worker three times per model with py-spy attached before timing. Sampled owner stacks in the preparation build covered 13.7 µs per read: 9.6 µs under `_admit_local`, including 5.2 µs in Python core admission, 2.6 µs storing payloads in the arena and 1.1 µs in publisher bookkeeping. The owner build's samples covered 1.1 µs per read, 0.7 µs of it under `_admit_local`, with no queued-frame or key decoding sample above 0.2 µs. The remaining owner CPU is outside sampled Python frames.

Frame decoding and dispatch (task 4.3) therefore stay in Python: after the owner transition they contribute no attributable cost above the sampler's resolution, so moving them would not remove measured work. The existing wire, admission-queue and attachment cases continue to cover malformed frames, queue saturation and socket fallback.

**Disposition: retained.** Owner CPU and group CPU improve in all six paired target observations, owner memory falls slightly, and the controls show no consistent adverse effect. The real-process shared-cache scenarios, lifecycle and fault cases pass against the native owner. The Python owner residency code had no remaining caller and was removed with the transition. The changelog records the owner CPU improvement.

## Candidate map

| Component                   | Current code path                                                                                                                                                                                                                                                                                   | Candidate and control                   | Disposition |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- | ----------- |
| Capture                     | `CursorCapture.append` encodes each document inside an envelope, slices the embedded bytes into a new object, and wraps them in `RawBSONDocument`; `finish` passes the wrapper list to `admit_namespace`, which encodes the whole list again; the native owner then retains that bytes object.      | `capture` cells in `CANDIDATES`         | Retained    |
| Key preparation             | Native lookups call the Python `canonicalize` operation for every discriminator and `order_sensitive_key` followed by `canonicalize` for identities; facade classification (`read_classification.py`, `read_validation.py`, `query_filters.py`) traverses the same filters before key construction. | `preparation` cells                     | Retained    |
| Shared residency            | `SharedCacheOwner` constructs the Python `CacheCore` with `IndexPublisher` and `ArenaPayloads`; `_drain_rings` touches the private `_lru`, and `_admit_local` holds `progress._lock` and `CacheCore._availability_lock` across validation and admission.                                            | `owner` cells                           | Retained    |
| Shared frames and dispatch  | `_frames` decodes each socket frame in Python; `select-*` requests decode keys through `decode_key` and `KeyCache.decode`; queued admissions use `decode_queued_frame`.                                                                                                                             | Attributed inside the `owner` benchmark | No change   |
| Event interpretation        | `_core/stream_events.py` routes each change event and `_core/stream_cost.py` records telemetry.                                                                                                                                                                                                     | Conditional on task 5.1                 | Pending     |
| Facade dispatch             | Sync/async `collection.py` and `cursors.py` bind sessions, classify requests, and call the core.                                                                                                                                                                                                    | Conditional on task 5.1                 | Pending     |
| Metadata, lifecycle, others | Collection/index/namespace metadata caches, health/backoff, stream supervision, configuration, snapshots, errors, OpenTelemetry, public wrappers.                                                                                                                                                   | Conditional on task 5.1                 | Pending     |
