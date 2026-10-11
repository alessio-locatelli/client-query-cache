# Concurrent worker workload registration, version 1

This registration freezes the protocol for comparing direct MongoDB reads with independent per-worker cache managers while reads and writes run together. The machine-readable values live in [config.json](config.json); this companion explains units, measures, rules and limits. The [design](../../../openspec/changes/archive/2026-10-11-benchmark-concurrent-worker-workload/design.md#workload-registration) records why each value was chosen.

**Status:** frozen. The frozen `config.json` has SHA-256 `2057af0088101622b441f977fbc9bd78397f2e023fafd8b092cc1e74d1b6d0bc`, which every comparison report must carry. Any change to this file or `config.json` after a comparison window runs requires a new registration version and fresh comparisons; earlier outcomes are retained.

## Units and scope

Durations are seconds, rates are aggregate application reads per second, memory is bytes (MiB means 1,048,576 bytes), and CPU is user plus system seconds. Request latency runs from each request's scheduled issue time to its completion on one host-wide monotonic clock, so queueing delay is included. One host runs every process; MongoDB runs in a disposable single-member replica set limited to 2 CPUs and 2 GiB.

## Paths and equivalent work

- `direct`: each worker reads through its own PyMongo client with primary read preference and majority read concern.
- `independent`: each worker owns a `CacheManager` with a 96 MiB budget, a 1 MiB maximum entry and its own database change stream.

Both paths use asyncio workers with four concurrent requests each, issue `find_one({"_id": key})`, and decode and checksum every result (CRC-32 of the payload combined with the document revision) without retaining it.

## Workload and data

| Parameter   | Value                                                                                                                                                                                                                |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Data        | 16,384 `primary` documents with a 4 KiB payload and nested BSON values, generated from seed 197 (the shared worker cache study's `primary` profile, about 4,370 encoded bytes each)                                  |
| Hot set     | The first 1,024 keys of the seed-197 permutation of the document keys, about 4.3 MiB encoded                                                                                                                         |
| Reads       | One aggregate open-loop schedule at the frozen rate; request ordinals go round-robin to workers, and each worker walks its own seeded permutation of the whole hot set, so no key is partitioned to a single worker  |
| Writes      | `floor(rate × window / 20)` `$inc revision` updates per window, evenly spaced and cycling through a seed-198 permutation of the hot set; a pool of four harness writer threads issues each one at its scheduled time |
| Workers     | 1 and 4 asyncio worker processes                                                                                                                                                                                     |
| Priming     | Before each window every worker reads the whole hot set, on both paths, then runs a 10 s untimed warmup at the frozen rate; priming time, CPU and memory are retained and excluded from window measures              |
| Smoke check | The 256-document `smoke` profile at 200 reads/s for 3 s after a 1 s warmup, at 1 and 4 workers; it checks the instrumentation only and is never reported as evidence                                                 |

## Calibration

Calibration uses both paths and is excluded from the comparison.

1. **Probes.** For each registered cell (asyncio, 1 and 4 workers), run three closed-loop windows per path of the read-only `hot` workload on the hot set, with fresh data and workers, a 10 s untimed warmup and 15 s of measurement. Throughput is completed reads divided by the longest worker's elapsed measurement time. Probes read only, because a closed loop has no offered rate from which to derive the write count.
2. **Selection.** The rate is `floor(0.75 × lowest probe throughput)` across both paths and both worker counts, capped at 6,000 reads/s.
3. **Duration.** Windows last `max(60, ceil(10,102 / rate))` seconds, where 10,102 is `ceil(10,000 / 0.99)`. A duration above 120 s makes the setup inconclusive.
4. **Validation.** Three open-loop repetitions of each `active` cell on both paths at the selected rate and duration, with writes. A window passes when at least 99% of offered reads complete inside the application window, no read fails, no request overflows the 256-request bound, at most 8 requests per worker remain outstanding at the window end, and the request latency population has at least 10,000 samples. Read-only probes can overestimate capacity under writes, so a failing validation halves the rate (floor) and validates again, with at most three rate attempts. A window that fails for a setup reason, including a write issued more than 250 ms late, makes the calibration inconclusive instead of lowering the rate.
5. **Freezing.** `--freeze` copies the validated rate and window into `config.json` and sets `status` to `frozen`. Every comparison report carries the frozen file's SHA-256.

## Phases and counterbalancing

| Phase    | Cells                              | Blocks | Loop |
| -------- | ---------------------------------- | -----: | ---- |
| `smoke`  | `active`, asyncio, 1 and 4 workers |      1 | open |
| `steady` | `active`, asyncio, 1 and 4 workers |     12 | open |

Even blocks run `direct` before `independent` and odd blocks the reverse, so each order runs six times. Every window recreates the data, clients, workers and caches. A failed window is retained with its reason; it is never retried or replaced.

## Deadlines and bounds

| Bound                                     | Value  |
| ----------------------------------------- | ------ |
| Group startup, including priming          | 120 s  |
| Worker drain after the application window | 10 s   |
| Group shutdown                            | 15 s   |
| Harness write dispatch lateness           | 250 ms |
| Outstanding requests per worker           | 256    |
| Clock drift during a window               | 5 ms   |

## Measures

Each window yields one value per measure and path. A window is excluded from comparison, and reported with its reason, when it failed for a setup reason, when its observed stream openings differ from one per worker on `independent` and none on `direct`, or when it fails the validation rule above (it is then overloaded).

| Measure                | Block statistic                                                       | Scope                                                                                     |
| ---------------------- | --------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- |
| Throughput             | Reads completed inside the application window divided by its duration | All workers                                                                               |
| Request latency        | P50, P95 and P99 of the pooled request latencies                      | All workers, one population per window                                                    |
| MongoDB CPU            | Container CPU over the window and drain                               | The replica-set container's cgroup                                                        |
| Worker CPU per request | Worker CPU over the window and drain divided by completed reads       | Worker processes, including each worker's embedded MongoDB byte proxy                     |
| Harness CPU            | Harness process CPU over the window and drain                         | Writer pool, clock observer, PSS sampler, byte proxies and orchestration                  |
| Group memory           | Mean (steady) and maximum (peak) of 200 ms simultaneous PSS sums      | Worker processes; PSS splits shared pages, so each page counts once                       |
| Cache outcomes         | Hit, miss and per-reason bypass counter deltas                        | Managers on `independent`; counts per window, never divided by requests or made exclusive |
| Stream openings        | Command-observed `$changeStream` aggregates                           | Worker clients                                                                            |
| Invalidation lag       | P50 and P95 of pooled captured lag                                    | Managers on `independent`                                                                 |

For each worker count, the analysis pairs `independent` with `direct` by block for every measure from throughput to group memory. It reports the ratio `mean_b(independent_b) / mean_b(direct_b)` and the delta `mean_b(independent_b − direct_b)`, each with a 95% percentile interval from 200,000 block-bootstrap draws with seed 197. Blocks with an excluded window on either path are left out, and the number of remaining pairs is reported. The analysis has no promotion gate.

## Invalidation lag clocks

Each manager keeps the latency of its last 1,000 invalidations (ten windows of 100 consecutive events). A raw lag is the worker host's wall clock when the manager applied the invalidation minus the change event's `wallTime`, which is the MongoDB server's wall clock when the write committed, at millisecond resolution. The harness samples `hello` to estimate the server-minus-host clock offset and adds it, so the reported lag is on the server clock. Each window also reports the offset and its uncertainty: half the sampling round trip plus 1 ms of quantization, widened by any drift during the window. A window whose drift exceeds 5 ms, whose host clock steps, or whose primary changes fails as a setup error. A lag percentile is reported only when the window pooled at least 200 captured events; otherwise the analysis states the shortfall.

## Excluded comparison

The registration has no shared Redis path: a Redis cache matches this library's freshness only with an invalidator that this project would have to build, so the comparison would not measure a deployment choice available to users. The [design](../../../openspec/changes/archive/2026-10-11-benchmark-concurrent-worker-workload/design.md#no-shared-redis-comparison) records the alternatives, and shared invalidation stays under [#87](https://github.com/alessio-locatelli/client-query-cache/issues/87).

## Limits

One host and a single-member replica set understate network latency and overstate the CPU that direct reads compete for. Four workers, the harness and two MongoDB CPUs share the host's logical CPUs. The workload has one database, uniform key popularity and 4 KiB documents; results make no claim about other working sets, synchronous workers, sharded clusters or other hosts.

## Calibration result

Calibration ran against MongoDB 8.0.4 from the draft configuration with SHA-256 `e447f37359fe82a50417f2963a84949ce70374ef1f2a04873b25a0770302026c`, at revision `2c1b6e158e2ef64800d9a07fcb3402afbe9eeddf`. While it ran, the branch was rebased onto a `main` whose only new commit changed the harness's MongoDB image to 8.3.11; the running harness had already started its replica set, so every calibration window used 8.0.4. The rebased commit `8e94e9667cd3bfa48b3b3b481336f215c3af5a76` differs from the calibrated revision only in the MongoDB image tags of the harness and the test suite. All 36 windows were healthy: 12 closed-loop probes and 24 open-loop validations. Throughput is reads/s over the three probe windows of each cell.

| Cell               | `direct` probes | `independent` probes |
| ------------------ | --------------: | -------------------: |
| asyncio, 1 worker  |     4,884–4,971 |        41,610–42,955 |
| asyncio, 4 workers |   12,378–12,491 |      162,510–164,505 |

The weakest probe, one direct worker, selected 3,663 reads/s. Its validation failed once: in the first repetition, the one-worker direct window ended with 9 requests outstanding, above the bound of 8, although it completed 99.996% of its reads inside the window. This is the overestimate that read-only probes were expected to produce under writes. The halved rate, 1,831 reads/s, passed all twelve windows, so the frozen rate is 1,831 reads/s with 60 s windows, which offer 109,860 reads and 5,493 writes per window. Every validation window met the sample floor with at least 109,860 latency samples. The largest write lateness across both attempts was 33.4 ms, within the 250 ms tolerance, and the slowest write took 0.40 s.

## Reproduction

From the repository root, after the [contributor setup](../../../CONTRIBUTING.md):

```console
source scripts/testcontainers-bridge.sh
uv run -- python -m benchmarks.stream_cost.shared_cache.run --smoke --config reports/concurrent-worker-workload/v1/config.json --output benchmark-reports/concurrent-worker-workload/smoke.json
uv run -- python -m benchmarks.stream_cost.shared_cache.run --calibrate-baselines --config reports/concurrent-worker-workload/v1/config.json --output benchmark-reports/concurrent-worker-workload/calibration.json
uv run -- python -m benchmarks.stream_cost.shared_cache.run --freeze benchmark-reports/concurrent-worker-workload/calibration.json --config reports/concurrent-worker-workload/v1/config.json
uv run -- python -m benchmarks.stream_cost.shared_cache.run --phase steady --config reports/concurrent-worker-workload/v1/config.json --output benchmark-reports/concurrent-worker-workload/steady.json
uv run -- python -m benchmarks.stream_cost.shared_cache.analysis benchmark-reports/concurrent-worker-workload/steady.json --config reports/concurrent-worker-workload/v1/config.json --phase steady --blocks 12
```

Use a new output path for every run; raw reports stay untracked. A run interrupted by the host can continue with `--resume <earlier report>` at the same revision, registration and `--only` limit. A report produced with `--only` is labelled exploratory, and the analysis rejects it.
