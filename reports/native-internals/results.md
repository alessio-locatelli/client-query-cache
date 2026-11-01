# Native internals results

This report records the evidence and per-component dispositions for the [migrate-remaining-hotpaths-to-rust](../../openspec/changes/archive/2026-11-01-migrate-remaining-hotpaths-to-rust/design.md) change. Builds, commands, and resource scope are registered in [plan.md](plan.md). Paths are relative to `src/client_query_cache/` unless prefixed otherwise.

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

## Remaining responsibilities

Task 5.1 inspected the retained owner build (`29106b20`) with bounded worker profiles of 256 hot reads per worker for identity, generic `find_one` and 16-document `find`, on independent and shared paths, plus a complete event-processing measurement. Profiles are instrumented elapsed time; the event measurement is uninstrumented process CPU.

| Component                        | Evidence                                                                                                                                                                                                                                                            | Disposition                                                                                                                           |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| Event routing and telemetry      | A manager processing 20,000 update events through its change stream used 696 µs of process CPU per processed event; routing one event, including the native write and invalidation telemetry, takes 2.24 µs, against 1.34 µs for decoding the event document alone. | No change: routing is 0.3% of the complete per-event cost, which getMore round trips and driver cursor handling dominate.             |
| Facade cursor construction       | Every cached `find()` binds its arguments with `inspect.Signature.bind` to detect unsupported options: 46–50 µs of a 172–179 µs instrumented hot read, on both paths.                                                                                               | Candidate: the parameters are all positional-or-keyword, so the supplied names follow from argument positions and keywords directly.  |
| Codec fingerprint in read shapes | Each generic `find_one` and `find` read traverses the collection's codec fingerprint again inside its read shape, including 12–14 abstract-base-class checks (4.8–6.9 µs instrumented).                                                                             | Candidate: the collection precomputes the fingerprint's canonical key, which the shape traversal returns unchanged.                   |
| Namespace metadata caches        | A local generic `find_one` reads the same namespace metadata twice, for eligibility and then for the default collation (about 1 µs each); shared reads perform three or four lookups that each re-check expiry at their own decision point.                         | Candidate for the local repeat only. Shared lookups stay: reusing one snapshot would move when an expired or refreshed entry applies. |
| Facade classification and keys   | Remaining session, read-profile and option checks cost 3–6 µs per read in Python and call driver internals that must stay in Python.                                                                                                                                | No change: no repeated structural traversal remains after task 3.                                                                     |
| Lifecycle, configuration, others | Manager construction, stream activation and supervision, health and backoff, snapshots, errors, OpenTelemetry and public wrappers run per manager, per stream event batch or on explicit inspection, not per read.                                                  | No change: none appears in the hot-read profiles.                                                                                     |

The dispatch candidate's cells are registered in `CANDIDATES` before its runtime change: hot 16 × 128-byte `find` on independent and shared managers, hot generic `find_one`, and the hot identity control.

## Facade dispatch

The dispatch candidate (`bdf96534`) combines the three candidate rows above: cursor construction derives the supplied option names from argument positions and keywords, collections keep their codec fingerprint's canonical key, and a local `find_one` reuses the metadata its eligibility check returned. It changes only Python, so its extension is the owner build's. It passed the preflight in 76 seconds. Its benchmark ran three counterbalanced blocks against the retained owner build from harness `bdf96534` in 174 seconds, with every window validated and every CPU component resolved.

| Cell (four workers)                                                    | Model | Paired change per block (owner → dispatch) | Median |
| ---------------------------------------------------------------------- | ----- | ------------------------------------------ | -----: |
| Target: hot 16-document `find`, independent, CPU per read              | sync  | −32.4%, −39.2%, −30.1%                     | −32.4% |
|                                                                        | async | −22.5%, −31.6%, −30.6%                     | −30.6% |
| Target P50 latency                                                     | sync  | −35.1%, −34.1%, −34.9%                     | −34.9% |
|                                                                        | async | −34.1%, −34.4%, −34.3%                     | −34.3% |
| Target: hot 16-document `find`, shared, worker plus owner CPU per read | sync  | −16.4%, −40.1%, −22.8%                     | −22.8% |
|                                                                        | async | −39.3%, −15.2%, −21.0%                     | −21.0% |
| Target P50 latency                                                     | sync  | −25.3%, −35.7%, −34.4%                     | −34.4% |
|                                                                        | async | −34.6%, −33.8%, −34.2%                     | −34.2% |
| Target: hot generic `find_one`, independent, CPU per read              | sync  | −4.9%, −24.1%, −5.5%                       |  −5.5% |
|                                                                        | async | +28.6%, −44.4%, −27.5%                     | −27.5% |
| Target P50 latency                                                     | sync  | −27.2%, −25.8%, +59.8%                     | −25.8% |
|                                                                        | async | +64.9%, −28.2%, −23.2%                     | −23.2% |
| Control: hot identity, independent, CPU per read                       | sync  | −5.7%, +23.6%, +32.7%                      | +23.6% |
|                                                                        | async | +17.8%, −9.9%, +4.8%                       |  +4.8% |
| Control P50 latency                                                    | sync  | +37.6%, +39.2%, +2.4%                      | +37.6% |
|                                                                        | async | +76.6%, −7.5%, +3.7%                       |  +3.7% |

Hot `find` CPU fell from 39.5–47.2 µs to 25.9–36.6 µs per read on both paths, and P95/P99 fell in every independent pair. Shared asynchronous tails moved in both directions (P95: −50.5%, +16.3%, +11.1%) while its P50 fell in every pair. Worker PSS stayed within 0.7%. In block 0 profiles, a synchronous shared `find` spent 125.2 µs of instrumented time per read on the owner build, 35.9 µs of it under `Signature.bind`; the dispatch build spent 92.9 µs with no binding frame.

The generic `find_one` and identity cells cost 5–18 µs per read and showed the same within-build bimodal windows as the preparation controls, so their adverse pairs are a specific signal that three short pairs cannot resolve. A narrowly affected recheck alternated the two installed builds four times with 16,384 reads per worker on independent managers, in 236 seconds:

| Recheck cell           | Model | Owner CPU per read (µs)    | Dispatch CPU per read (µs) | P50 latency (µs), owner → dispatch |
| ---------------------- | ----- | -------------------------- | -------------------------- | ---------------------------------- |
| Hot generic `find_one` | sync  | 11.46, 11.31, 11.69, 11.08 | 9.08, 9.74, 10.24, 10.18   | 10.18–10.24 → 7.59–7.69            |
|                        | async | 13.18, 11.85, 13.88, 12.06 | 9.93, 9.89, 10.31, 9.58    | 11.01–11.17 → 8.27–8.59            |
| Hot identity           | sync  | 6.97, 5.59, 5.65, 7.00     | 5.64, 7.22, 5.84, 6.04     | 4.89–4.96 → 4.74–4.87              |
|                        | async | 6.25, 6.25, 6.31, 6.83     | 6.93, 6.10, 6.53, 6.58     | 5.55–5.59 → 5.38–5.48              |

Every dispatch `find_one` round uses less CPU than every owner round, with P50 about 25% lower. Every identity P50 is below the owner range and the CPU distributions overlap, so the recheck finds no identity regression and attributes the short-run control signal to window noise.

**Disposition: retained.** Hot `find` improves in all twelve paired CPU and P50 observations on both paths, the recheck confirms the generic `find_one` improvement, and the identity control shows no regression. The facade-dispatch and metadata rows are resolved by this candidate; shared metadata lookups stay as recorded above. The changelog records the cached-read improvement.

## Combined campaign

The registered campaign compared M (`c931b679`, wheel `45a63471…`, extension `4ef9fa15…`, PyMongo 4.18.3) with F (`c02c7f27`, wheel `3783da9b…`, extension `3e4f79cb…`, PyMongo 4.19.0) from harness `9c08dc15`. Blocks 0–4 ran public, memory and contention components in M/F, F/M, M/F, F/M, M/F order in 8,807 seconds, 849–913 seconds per run; every window validated, resolved its CPU and recorded the same hits, misses and bypasses in all ten runs. F's commit precedes a second rebase onto main that changed only CI and container tool versions; the rebased branch's package sources are identical.

M stays at the registered commit, so every M→F difference includes the PyMongo and development-package update. The direct cells, which read through PyMongo without the library, measure that update: their median CPU per read changed between −2.9% and +0.7%, and their latency medians between −1.2% and +1.9%. The largest direct signal was the asynchronous cold 48-element `$in` read, with P95 +12.9%, P99 +19.2% and throughput −3.8%; it runs no library code and is not attributed to this change.

| Cell                                                                | Model | CPU per read M → F (µs, median) | CPU change            | P50 change            | P99 change             |
| ------------------------------------------------------------------- | ----- | ------------------------------: | --------------------- | --------------------- | ---------------------- |
| `find_one` by `_id`, hot independent                                | sync  |                       6.4 → 5.8 | −9.7% [−19.5, +0.6]   | −8.6% [−9.5, −6.5]    | −12.6% [−31.6, −9.4]   |
| `find_one` by `_id`, hot independent                                | async |                       7.0 → 7.4 | −2.4% [−20.9, +16.0]  | −5.4% [−14.3, −3.0]   | −7.6% [−18.8, +23.2]   |
| `find_one` by `_id`, hot shared                                     | sync  |                       7.0 → 5.8 | −14.0% [−22.9, −7.8]  | −5.0% [−25.5, −3.1]   | −5.7% [−9.6, +3.0]     |
| `find_one` by `_id`, hot shared                                     | async |                       6.9 → 6.1 | −16.6% [−28.4, −2.1]  | −3.8% [−24.5, −2.5]   | −7.3% [−21.2, +0.9]    |
| `find_one` by `_id`, cold independent                               | sync  |                   175.1 → 179.0 | +0.3% [−0.2, +3.9]    | +0.2% [−1.8, +2.3]    | −8.3% [−18.0, +15.0]   |
| `find_one` by `_id`, cold independent                               | async |                   284.3 → 283.9 | −0.2% [−4.6, +3.6]    | −0.5% [−4.1, +4.0]    | −13.4% [−29.6, +142.6] |
| generic `find_one`, hot independent                                 | sync  |                      17.6 → 8.8 | −51.2% [−52.9, −47.8] | −51.7% [−53.0, −51.1] | −54.7% [−68.9, −52.5]  |
| generic `find_one`, hot independent                                 | async |                      18.3 → 9.9 | −45.7% [−51.8, −34.8] | −49.7% [−50.3, −49.4] | −47.9% [−60.9, −31.3]  |
| generic `find_one`, hot shared                                      | sync  |                      17.2 → 9.4 | −45.5% [−46.4, −37.8] | −40.9% [−41.1, −40.1] | −45.4% [−51.6, −42.0]  |
| generic `find_one`, hot shared                                      | async |                     19.4 → 11.0 | −43.4% [−45.3, −40.4] | −38.6% [−39.8, −38.1] | −40.2% [−42.1, −39.0]  |
| generic `find_one`, cold independent                                | sync  |                   220.7 → 204.5 | −8.2% [−12.6, −6.8]   | −4.5% [−8.7, −3.3]    | −15.8% [−31.9, +17.3]  |
| generic `find_one`, cold independent                                | async |                   338.9 → 319.5 | −6.6% [−15.6, −4.3]   | −4.8% [−15.1, −2.0]   | −2.5% [−42.8, +14.8]   |
| 16-document `find`, hot independent                                 | sync  |                     52.1 → 43.1 | −17.3% [−43.5, −9.8]  | −30.6% [−34.7, +9.9]  | −29.2% [−50.4, −24.6]  |
| 16-document `find`, hot independent                                 | async |                     50.8 → 39.5 | −23.9% [−24.9, −19.4] | −31.5% [−32.2, −28.9] | −24.9% [−33.4, −13.1]  |
| 16-document `find`, hot shared                                      | sync  |                     57.2 → 37.5 | −34.3% [−48.4, −27.7] | −33.2% [−36.6, −32.4] | −31.0% [−52.7, −27.1]  |
| 16-document `find`, hot shared                                      | async |                     54.2 → 38.7 | −29.9% [−36.4, −20.1] | −29.6% [−32.3, −28.3] | −28.4% [−51.9, −13.8]  |
| 16-document `find`, cold independent                                | sync  |                   402.9 → 340.9 | −14.5% [−16.8, −3.2]  | −9.1% [−11.1, +5.0]   | −13.0% [−17.2, +34.2]  |
| 16-document `find`, cold independent                                | async |                   539.4 → 472.4 | −12.4% [−14.6, −5.2]  | −7.6% [−10.4, +2.0]   | −4.4% [−14.2, +25.4]   |
| small generic `find_one`, 64,000 keys, hot independent              | sync  |                      12.2 → 8.5 | −30.7% [−42.0, +8.5]  | −26.1% [−27.2, −24.9] | −38.7% [−86.6, +152.5] |
| small generic `find_one`, 64,000 keys, hot independent              | async |                     11.6 → 10.0 | −15.0% [−26.2, −1.5]  | −24.0% [−24.2, −14.1] | −11.3% [−39.3, +10.4]  |
| small generic `find_one`, 64,000 keys, cold independent             | sync  |                   190.1 → 182.4 | −4.7% [−5.3, −3.3]    | −0.4% [−2.3, +3.0]    | −9.1% [−17.7, +5.5]    |
| small generic `find_one`, 64,000 keys, cold independent             | async |                   301.0 → 296.8 | −2.3% [−2.9, −0.7]    | +1.3% [−0.1, +3.6]    | +2.3% [−5.0, +6.3]     |
| generic `find_one`, 48-element `$in`, 64,000 keys, hot independent  | sync  |                     44.6 → 27.7 | −36.6% [−43.5, −31.6] | −43.3% [−44.0, −42.7] | −31.4% [−52.5, +41.3]  |
| generic `find_one`, 48-element `$in`, 64,000 keys, hot independent  | async |                     45.4 → 27.9 | −40.6% [−43.7, −38.6] | −43.1% [−43.2, −42.1] | −12.3% [−59.1, −9.8]   |
| generic `find_one`, 48-element `$in`, 64,000 keys, cold independent | sync  |                   272.6 → 232.0 | −13.4% [−15.9, −13.1] | −5.5% [−8.0, −4.8]    | −9.9% [−20.2, +11.3]   |
| generic `find_one`, 48-element `$in`, 64,000 keys, cold independent | async |                   391.1 → 348.2 | −10.6% [−13.5, −7.2]  | −5.2% [−8.1, −1.7]    | −8.7% [−11.7, +7.9]    |

Cached `find()` and generic `find_one()` reads improve in every hot cell on both paths, and their cold misses use 2–15% less CPU. Hot `_id` reads keep the bimodal windows recorded for the candidate controls: their P50 fell in every pair, and the asynchronous process-local CPU range spans zero. Cold `_id` misses, dominated by the MongoDB round trip, are unchanged. Owner PSS in hot shared cells moved by −0.8 to +0.3 MiB.

**Equal-residency memory.** Each memory checkpoint holds the same entries and payload bytes in both builds. Increments are cached-manager PSS above its baseline, with medians over the five runs:

| Scenario, synchronous                     | Resident entries | M warm (MiB) | F warm (MiB) | F2 warm (MiB) | M close (MiB) | F close (MiB) |
| ----------------------------------------- | ---------------: | -----------: | -----------: | ------------: | ------------- | ------------- |
| Documents                                 |           14,001 |        67.31 |        67.52 |         67.08 | 67.34–74.62   | 65.52–73.85   |
| Small generic `find_one` results          |           64,001 |        38.36 |        40.14 |         38.18 | 10.66–15.33   | 3.48–4.30     |
| Generic `find_one`, 48-element `$in` keys |           64,001 |       262.48 |       264.33 |        262.39 | 30.45–37.63   | 19.16–22.67   |
| Five fill/close cycles, last fill         |           17,772 |        10.99 |        10.69 |         10.13 | —             | —             |

For documents, small entries and large keys, asynchronous managers show the same warm increments within 0.07 MiB. F held 1.8 MiB more than M for 64,001 small entries in every pair, about 29 bytes per entry, which the F2 correction below removes. After close, F retains 6.8–27.4 MiB less than M for small entries and large keys in every pair; document close remains allocator-bimodal in both builds, as in the [previous adoption campaign](../native-process-local-cache/results.md#ordinary-wheel-adoption).

**Contention.** Each one- and four-thread window completed 80,000 reads at the offered 4,000 reads/s against 1,000 writes, with 998–999 origin `find` commands and 1,000 `getMore` commands in both builds and 37–47 overlapping invalidations. CPU per read changed −1.7% [−3.3, +16.4] with one thread and −1.4% [−8.3, +7.1] with four; P99 changed −1.1% [−13.7, +8.8] and +1.1% [−7.8, +13.2]. No consistent effect is established.

**Tests.** The existing selection of 4,397 node IDs ran 4,395 passing tests and one real-server skip, with the one registered case deselected, in 335.0 seconds of wall time and 419.0 child CPU-seconds for M and 337.4 seconds and 420.8 CPU-seconds for F. The 155 added tests took 27.6 seconds and 12.1 CPU-seconds on F. One pair is a regression control; it establishes no test-speed change. Two first attempts are excluded. During each, the example tests rebuilt the checkout's native extension inside its source overlay ([issue #391](https://github.com/alessio-locatelli/client-query-cache/issues/391)), so the overlay no longer matched the wheel (M: 350.8 seconds); both were repeated after restoring the wheel's extension, and neither repetition rebuilt it. F's first attempt also failed `tests/shared_cache/test_adapter_paths.py::test_handshakes_accept_two_descriptors_from_one_reply[split-reply-sync]`: the worker's descriptor set held one extra descriptor after the test ([issue #390](https://github.com/alessio-locatelli/client-query-cache/issues/390)). The case passed in five isolated and three whole-file reruns; this change does not modify it.

### Entry layout correction

The memory difference traced to the native entry layout: since the shared-owner transition, every entry's payload field could hold a 32-byte arena block, which widened process-local entries that never use the arena. F2 (`ed92c9c2`) keeps arena blocks in the owner's residency table and restores the one-reference payload field. A paired F/F2 check in F/F2, F2/F, F/F2 order reran the memory component with the owner admission cells, whose arena storage moved, and a hot process-local control in 2,318 seconds:

| Observation                                                      | Model | F → F2                            |
| ---------------------------------------------------------------- | ----- | --------------------------------- |
| Warm increment, 64,001 small entries                             | both  | 40.11–40.19 → 38.18–38.24 MiB     |
| Warm increment, 64,001 large-key entries                         | both  | 264.32–264.38 → 262.37–262.42 MiB |
| Warm increment, 14,001 documents                                 | both  | 67.47–67.56 → 67.07–67.14 MiB     |
| Cold `_id` reads, shared, drained admissions: group CPU per read | sync  | −2.9% [−4.5, −2.3]                |
|                                                                  | async | −3.4% [−5.5, +4.2]                |
| Same cells: owner CPU per read                                   | sync  | −3.6% [−5.3, −2.8]                |
|                                                                  | async | −5.1% [−7.2, +2.4]                |
| Control: hot generic `find_one`, independent, CPU per read       | sync  | −37.2% [−39.8, −30.0]             |
|                                                                  | async | −2.6% [−11.0, +14.7]              |
| Control: hot `_id` reads, shared, CPU per read                   | sync  | +10.2% [−4.5, +15.6]              |
|                                                                  | async | −13.1% [−24.9, +5.9]              |

Every target window drained 4,096 admitted admissions. The synchronous `find_one` control's F windows sat in the upper mode of its bimodal windows (11.8–13.9 µs against 8.8 µs in the campaign). The synchronous shared `_id` control is a specific adverse signal; a recheck alternated the two builds eight times with 16,384 reads per worker. F used 5.21–6.96 µs and F2 5.10–6.77 µs per read, with F2 lower in seven of eight rounds, and P50 was 4.49–6.95 µs for F and 4.44–5.03 µs for F2. The recheck finds no regression; those hits are served by the unchanged shared reader.

**Disposition: retained.** F2 is the final build. It matches or improves on M's resident memory at equal residency and keeps F's measured effects in the cells it changes.

### Component decisions

| Component                         | Short-run evidence                                        | Campaign                                                                   | Decision  |
| --------------------------------- | --------------------------------------------------------- | -------------------------------------------------------------------------- | --------- |
| Encoded capture (D2)              | [Capture](#capture)                                       | Cold `find` misses −12% to −15% CPU                                        | Retained  |
| Native key preparation (D3)       | [Preparation](#preparation)                               | Hot generic `find_one` −37% to −51% CPU                                    | Retained  |
| Native shared owner (D4)          | [Shared owner](#shared-owner)                             | Hot shared reads improve; owner PSS within 0.8 MiB; layout corrected in F2 | Retained  |
| Frames and dispatch in the owner  | [Shared owner](#shared-owner)                             | —                                                                          | No change |
| Event routing and telemetry       | [Remaining responsibilities](#remaining-responsibilities) | —                                                                          | No change |
| Facade dispatch and metadata (D5) | [Facade dispatch](#facade-dispatch)                       | Hot `find` −17% to −34% CPU on both paths                                  | Retained  |

## Candidate map

| Component                   | Current code path                                                                                                                                                                                                                                                                                   | Candidate and control                   | Disposition                                                   |
| --------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- | ------------------------------------------------------------- |
| Capture                     | `CursorCapture.append` encodes each document inside an envelope, slices the embedded bytes into a new object, and wraps them in `RawBSONDocument`; `finish` passes the wrapper list to `admit_namespace`, which encodes the whole list again; the native owner then retains that bytes object.      | `capture` cells in `CANDIDATES`         | Retained                                                      |
| Key preparation             | Native lookups call the Python `canonicalize` operation for every discriminator and `order_sensitive_key` followed by `canonicalize` for identities; facade classification (`read_classification.py`, `read_validation.py`, `query_filters.py`) traverses the same filters before key construction. | `preparation` cells                     | Retained                                                      |
| Shared residency            | `SharedCacheOwner` constructs the Python `CacheCore` with `IndexPublisher` and `ArenaPayloads`; `_drain_rings` touches the private `_lru`, and `_admit_local` holds `progress._lock` and `CacheCore._availability_lock` across validation and admission.                                            | `owner` cells                           | Retained                                                      |
| Shared frames and dispatch  | `_frames` decodes each socket frame in Python; `select-*` requests decode keys through `decode_key` and `KeyCache.decode`; queued admissions use `decode_queued_frame`.                                                                                                                             | Attributed inside the `owner` benchmark | No change                                                     |
| Event interpretation        | `_core/stream_events.py` routes each change event and `_core/stream_cost.py` records telemetry.                                                                                                                                                                                                     | Conditional on task 5.1                 | No change                                                     |
| Facade dispatch             | Sync/async `collection.py` and `cursors.py` bind sessions, classify requests, and call the core.                                                                                                                                                                                                    | `dispatch` cells                        | Retained                                                      |
| Metadata, lifecycle, others | Collection/index/namespace metadata caches, health/backoff, stream supervision, configuration, snapshots, errors, OpenTelemetry, public wrappers.                                                                                                                                                   | `dispatch` cells                        | Retained for the local `find_one` repeat; no change otherwise |
