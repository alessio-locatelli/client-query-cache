# Shared worker cache registration, version 3

This registration freezes the decision protocol for the shared worker cache investigation before any shared-candidate timing. The machine-readable values live in [config.json](config.json); this companion explains units, estimands, rules and limits. The [design](../../../openspec/changes/investigate-shared-worker-cache/design.md#measurement-protocol) records the rationale and the promotion thresholds that these values encode.

**Status:** draft pending baseline-only calibration. [Version 1](../v1/registration.md) and [version 2](../v2/registration.md) ended without a frozen workload; see [registration history](#registration-history). `frozen.rates`, `frozen.window_seconds` and `frozen.calibration_summary` are `null` until a validated calibration is frozen with `--freeze`. Candidate phases refuse to run against an unfrozen registration. Any change to this file or `config.json` after a candidate measurement starts requires a new registration version and fresh affected comparisons; earlier outcomes are retained.

## Units and scope

Durations are seconds, rates are aggregate application reads per second, memory is bytes (MiB means 1,048,576 bytes), CPU is user plus system seconds. Latency is measured from each request's scheduled issue time to completion on one host-wide monotonic clock, so queueing delay is included. One host runs every process; MongoDB runs in a disposable single-member replica set limited to 2 CPUs and 2 GiB.

## Paths and equivalent work

- `direct`: each worker reads through its own PyMongo client with primary read preference and majority read concern.
- `independent`: each worker owns a supported `CacheManager` with a 96 MiB budget, 1 MiB maximum entry and its own database stream.
- `shared`: an application-owned research owner process holds one `CacheCore`, one change stream per active database and a 96 MiB group budget. Workers attach through the research adapters in `benchmarks/stream_cost/shared_cache/`, keep their own clients for native reads and decode stored BSON locally.

Every path performs the same decode and checksum work per result (CRC-32 of the payload combined with the document revision) without retaining results. Every worker primes by reading the complete hot set before a window, including the direct path; priming duration, CPU and memory are retained as startup evidence and excluded from window measurements.

## Workload and data

| Profile   | Documents | Payload | Read                                                          | Encoded entry bytes (measured) |
| --------- | --------: | ------: | ------------------------------------------------------------- | -----------------------------: |
| `primary` |    16,384 |   4 KiB | `find_one({"_id": key})`                                      |  4,366–4,371; 71,600,453 total |
| `large`   |     1,088 |  64 KiB | `find_one({"_id": key})`                                      |    65,809 each; ≈71.6 MB total |
| `find16`  |    16,384 |   4 KiB | `find({"attributes.category": c}).sort("_id").limit(16)`, 64c |              ≈70 KB per result |
| `smoke`   |       256 |   4 KiB | `find_one({"_id": key})`                                      |           Instrumentation only |

Documents contain nested BSON values (Decimal128 price, string tags, nested float dimensions, a datetime) generated from seed 197. The primary hot set is 68.28 MiB of encoded entries, which fits the 96 MiB budget of each independent manager and of the single group. Eight independent managers configure 768 MiB in total; the measured eight-worker independent group retained about 1.04 GiB PSS in an exploratory probe, well within the 62 GiB host. Request keys follow a seeded permutation of the profile's keys, partitioned round-robin across workers. Active windows apply 200 seeded `$inc revision` updates evenly across the frozen active duration.

## Baseline-only calibration

Calibration uses only `direct` and `independent` and is excluded from promotion inference.

1. **Probes.** For every cell listed under `calibration.families`, run three closed-loop probe windows per baseline path with fresh data and workers, per-worker concurrency 4, 10 s untimed warmup (none for cold) and 15 s measurement. Cold probes end after 10,000 distinct identities or 15 s. Active probes include the nominal 200 updates per 60 s cadence. Throughput is completed reads divided by the longest worker's elapsed measurement time.
2. **Selection.** Each family's rate is `floor(0.75 × lowest probe throughput)` across both paths and every family cell, capped at 6,000 (primary), 1,000 (cold) and 500 (sensitivity); cold and sensitivity rates are also capped at the selected primary rate.
3. **Durations.** Hot windows last `max(30, ceil(10,102 / rate))` seconds, active windows `max(60, ceil(2 × 10,102 / rate))` so each model of the mixed group offers the floor, sensitivity windows `max(30, ceil(10,102 / rate))`, and cold windows `10,000 / cold rate`. 10,102 is `ceil(10,000 / 0.99)`. A duration above 120 s makes the setup inconclusive.
4. **Validation.** Three open-loop repetitions of every family cell for both baseline paths at the selected rate and frozen duration. A window passes when at least 99% of offered reads complete inside the application window, no read fails, no request overflows the 256-request bound, at most 8 requests per worker remain outstanding at the window end, every gated percentile population (per model for the mixed group) has at least 10,000 completed samples, and cold windows complete all 10,000 identities. A failing family halves its rate (floor) and revalidates, with at most three rate attempts. A window that fails for a setup reason (container, clock or process failure) makes the calibration inconclusive instead of lowering the rate. Closed-loop probes deliberately saturate the host, so they record the harness write lateness without enforcing the 250 ms dispatch tolerance; every open-loop window enforces it and records the largest lateness.
5. **Freezing.** `--freeze` copies the validated rates, durations and calibration revision into `config.json` and sets `status` to `frozen`. The frozen file's SHA-256 is the configuration digest that candidate reports carry.

Active schedules keep 200 updates per run, so their cadence scales with the frozen duration; validation and candidate windows replay the same seeded read and write schedules. Samples from different runs are never pooled to meet the 10,000 floor.

Calibration may run before the candidate prototype's own checks are complete, because it uses no candidate code path and no candidate result can influence it.

## Candidate selection and feasibility

The first and only built candidate is the socket owner described under paths. The bounded checks below select the experiment order; they are not decision evidence.

| Alternative                                            | Check                                                                                                                                                                                                                                                                                                                                                                                       | Disposition                                                                                                                                            |
| ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `multiprocessing` manager with a coarse `select` proxy | Supports independently started processes through an address and authkey, but transports arguments with pickle, has no asyncio client, and needs a thread executor for event-loop workers. The exploratory diagnostic compares one coarse proxy hit against one socket hit. The proxy control omits the owner's availability, progress and epoch checks, so it bounds the proxy's best case. | Control only. A pickle endpoint is never exposed to workers.                                                                                           |
| Coordinator-managed shared-memory payloads             | `multiprocessing.shared_memory` segments are shareable by name, but independently started processes need explicit name exchange, untracked attachment to avoid resource-tracker unlinking, and a pin/reclaim protocol. Selection and its guards still need one owner round trip.                                                                                                            | Possible second candidate only through the payload trigger below.                                                                                      |
| LMDB payload store                                     | Reader transactions give stable mapped payload views and one writer. Used only as the owner's payload store keyed by entry token, it keeps `CacheCore` as the single eviction, generation, alias and selection algorithm; moving validity checks into LMDB would create a second cache algorithm and is rejected.                                                                           | Preferred second candidate over custom shared memory when its dependency installs for the measured Python; selection still costs one owner round trip. |
| Thread-executor asyncio adapter                        | Wraps the blocking socket endpoint in `asyncio.to_thread`; the diagnostic compares it with the event-loop socket adapter.                                                                                                                                                                                                                                                                   | The prototype uses event-loop sockets; the executor is a diagnostic control.                                                                           |

**Second-candidate trigger.** A payload-store candidate is built only if task 2.2 profiling at a failing four- or eight-worker cell attributes at least half of the shared path's excess over independent managers (hit latency or CPU per completed request) to payload-proportional work: frame encoding and decoding of entry bytes, socket copies and owner sends. The profile compares the `primary` and `large` profiles and the measured owner busy time per request. Owner round-trip overhead that does not scale with payload size cannot trigger it, because both payload-store candidates keep that round trip.

**Platform and dependencies.** The prototype needs only the standard library (`socket`, `selectors`, `asyncio`, `fcntl`) and BSON from PyMongo. Unix-domain sockets and `fcntl` locks restrict shared mode to POSIX hosts; this registration measures Linux only, and standalone managers keep their existing platform support.

## Phases and counterbalancing

| Phase          | Cells                                                                          | Blocks or windows      | Loop     |
| -------------- | ------------------------------------------------------------------------------ | ---------------------- | -------- |
| `smoke`        | hot/sync, active/mixed, cold/async at 2 workers, 256 documents, 200 reads/s    | 1                      | open     |
| `screening`    | hot, sync and async, 1/4/8 workers, three paths                                | 6 exploratory blocks   | open     |
| `confirmation` | hot, sync and async, 4/8 workers, three paths                                  | 12 fresh blocks        | open     |
| `capacity`     | hot, sync and async, 1/4/8 workers, per-worker concurrency 1/4/16, three paths | 3 windows of 15 s      | closed   |
| `active`       | active, sync and async at 4/8 workers plus a 4 sync + 4 async mixed group      | 12 blocks              | open     |
| `cold`         | cold, sync and async, 4/8 workers                                              | 12 blocks              | open     |
| `sensitivity`  | `large` and `find16`, sync and async, 8 workers                                | 3 blocks               | open     |
| `fault`        | 2 sync + 2 async workers, every case in `fault_cases`                          | 5 repetitions per case | scripted |

Within block `b`, paths run in the `b mod 6`-th lexicographic permutation of `(direct, independent, shared)`, so twelve blocks use every order twice. Every window recreates the data, clients, workers, owner and cache. Calibration probes and validations alternate the two baseline orders by window parity.

Each phase writes its own untracked report under `benchmark-reports/shared-worker-cache/`. A failed window is retained with its reason; it is never retried or replaced.

## Deadlines and bounds

| Bound                                     | Value                                  |
| ----------------------------------------- | -------------------------------------- |
| Group startup, including priming          | 120 s                                  |
| Worker drain after the application window | 10 s                                   |
| Group shutdown                            | 15 s                                   |
| Harness write dispatch lateness           | 250 ms                                 |
| Shared RPC completion from issuance       | 100 ms                                 |
| Upstream-progress expiry                  | 3 s                                    |
| Admission capture lifetime                | 30 s                                   |
| Per connection                            | 4 MiB queued bytes, 256 queued replies |
| Group                                     | 64 connections, 4,096 captures         |
| Frame                                     | 1 MiB entry plus 64 KiB overhead       |
| Safe readiness after owner restart        | 5 s                                    |

## Estimands and inference

For each required cell and block, the report retains one statistic per path. Gates use paired blocks:

- **Ratio estimands** are `mean_b(shared_b) / mean_b(baseline_b)` over the cell's blocks.
- **Delta estimands** are `mean_b(shared_b − baseline_b)`.

Promotion inference resamples whole blocks with replacement: 200,000 draws with seed 197, percentile intervals at nominal 95% for the single candidate's all-must-pass conjunction (97.5% each if a second candidate becomes eligible), and the interval's upper end as the bound. The verdict must be unchanged with seed 1970 and with each block left out (20,000 draws each); a changed verdict is inconclusive. No additional sampling is permitted beyond twelve confirmation blocks.

| Gate                     | Block statistic and observable input                                                                                                 | Criterion                                                      |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------- |
| Group memory             | Mean of 200 ms simultaneous PSS sums over workers and owner (`memory.steady_group_pss_bytes`)                                        | shared/independent ≤ 0.75 at 4 and 8 workers                   |
| Peak memory              | Maximum PSS sum (`memory.peak_group_pss_bytes`)                                                                                      | shared/independent ≤ 1.10                                      |
| Application plus MongoDB | Steady group PSS plus container memory (`server_memory_bytes`)                                                                       | shared/independent ≤ 1.10                                      |
| Hit latency              | P95 and P99 of pooled request latency in hot windows, valid only when cached outcome counters show every completed request was a hit | shared/direct ≤ 0.75 (P95) and ≤ 1.0 (P99)                     |
| Request latency          | P99 of pooled request latency in hot and active windows, per model for the mixed group                                               | shared/independent ≤ 1.25 and delta ≤ 1 ms                     |
| Miss latency             | P95 and P99 of pooled request latency in cold windows, valid only when every completed cached request was a miss                     | delta to direct ≤ 1 ms                                         |
| Completion               | `completed / offered` with no errors or overflow, within bounded drain                                                               | ≥ 0.99 in every window                                         |
| Total CPU                | Worker, owner and MongoDB CPU over the window and drain, divided by completed reads; harness CPU reported separately                 | shared/independent ≤ 1.10                                      |
| MongoDB traffic          | Proxy bytes of worker and owner MongoDB paths                                                                                        | shared/independent ≤ 1.10                                      |
| Stream ownership         | Command-observed stream openings: one owner stream for `shared`, one per worker for `independent`, none for `direct`                 | exact                                                          |
| Invalidation lag         | P95 of pooled captured lag per run (owner for `shared`, all workers for `independent`), adjusted by the initial clock offset         | upper ≤ 500 ms after clock expansion; delta ≤ 50 ms            |
| Capacity                 | Closed-loop throughput at each staircase point                                                                                       | shared ≥ 0.9 × independent and ≥ 1.25 × direct in every window |
| Safety and recovery      | Deterministic scenarios in `tests/shared_cache/` and the fault phase                                                                 | every case passes; readiness ≤ 5 s                             |

Missing data: a required cell with a failed or missing block fails the conjunction; failed cells are never averaged away or imputed. Capacity, sensitivity and fault results are descriptive and make no simultaneous confidence claim.

**Screening futility rule.** Screening point estimates use the same estimands over its six exploratory blocks at 4 and 8 workers for both models. If any point estimate violates its criterion, or any safety check fails, the candidate stops with that recorded reason and no confirmation is collected. Screening can never promote a candidate.

The capacity staircase stops increasing concurrency for a path after two consecutive points fail to raise throughput by 5% or violate the request-latency gate.

## Limits

The single-host, single-member replica set may overstate or understate practical benefit. Eight worker processes, an owner process, the harness and two MongoDB CPUs share eight logical CPUs, so eight-worker cells are close to host saturation. Results make no claim about sharded clusters, other hosts or other working-set shapes. PSS divides shared pages proportionally; container memory is Podman's cgroup usage, which includes page cache, and is never added to overlapping process counters. Embedded instrumentation (each process's MongoDB byte proxy) remains in its owner's CPU counter.

## Prototype safety scenarios

`tests/shared_cache/` runs the [ordering, uncertainty and restart](../../../openspec/changes/investigate-shared-worker-cache/design.md#ordering-uncertainty-and-restart) cases against a real owner process, real worker processes where process death matters, bounded transport limits and a disposable replica set: owner restart and duplicate startup, paused owner, stalled watch with live RPC, stream interruption, lost resume history, a killed worker holding a capture, a replacement worker, a slow reader, malformed or unauthorized peers, owner exit during stream activation, cancellation of an in-flight asyncio selection, inherited attachments, capture bounds and processed invalidations. Each case asserts native results, rejected obsolete captures, released owner state or continued event-loop progress. Run them before collecting decision evidence:

```console
just pytest -- tests/shared_cache tests/benchmark/stream_cost/test_shared_cache_run.py tests/benchmark/stream_cost/test_shared_cache_run_integration.py
```

## Registration history

Version 1's first calibration attempt stopped at its twelfth probe when the socket-activated Podman API dropped a container-statistics connection; the runner now retries such a read before reporting a setup failure. Its second attempt completed every probe except the first-block active asyncio four-worker direct probe, whose harness write was issued more than 50 ms late while the closed-loop probe saturated the host. Version 1 required that calibration to stop as inconclusive, and no rate was derived from it. Version 2 changed only the probe write rule.

Version 2's calibration completed all 114 probes, all healthy. Its primary-family validation at 2,656 reads/s then stopped as inconclusive: seven of thirty open-loop active windows issued a harness write more than 50 ms late, although the healthy windows' largest lateness was 0.1–28.8 ms and the late windows were spread across paths, models and worker counts. The harness thread that issues writes shares its interpreter with the clock observer, PSS sampler and byte proxies, so occasional stalls longer than 50 ms are an instrumentation limit rather than overload; one one-worker synchronous direct hot window also completed only 97.4% of its reads in the window, which the registered rule treats as overload.

Version 3 raises the dispatch tolerance to 250 ms, below the 300 ms nominal spacing of active writes, and records each window's largest write lateness. Invalidation lag is measured from each event's server commit time, so dispatch lateness does not change the lag estimand. Version 3 reuses version 2's 114 healthy closed-loop probes (`--reuse-probes`), because probes never enforce the tolerance and their workload, code path and selection rule are unchanged; validation and every later window run fresh under version 3. All attempts' raw reports remain untracked.

## Reproduction

From the repository root, after the [contributor setup](../../../CONTRIBUTING.md):

```console
source scripts/testcontainers-bridge.sh
uv run -- python -m benchmarks.stream_cost.shared_cache.run --smoke --output benchmark-reports/shared-worker-cache/smoke.json
uv run -- python -m benchmarks.stream_cost.shared_cache.run --calibrate-baselines --config reports/shared-worker-cache/v3/config.json --reuse-probes benchmark-reports/shared-worker-cache/v2-calibration-b.json --output benchmark-reports/shared-worker-cache/baseline-calibration.json
uv run -- python -m benchmarks.stream_cost.shared_cache.run --freeze benchmark-reports/shared-worker-cache/baseline-calibration.json
uv run -- python -m benchmarks.stream_cost.shared_cache.run --phase screening --output benchmark-reports/shared-worker-cache/screening.json
```

Use a new output path for every run; raw reports stay untracked. A run interrupted by the host can continue with `--resume <earlier report>` at the same revision and registration: completed windows are copied in their planned order and the remaining windows run fresh. Windows are independent, so resuming changes neither schedules nor inference.
