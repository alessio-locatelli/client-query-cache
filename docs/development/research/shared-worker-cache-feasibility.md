# Shared worker cache feasibility

This study asked whether a group of application worker processes on one host could share one resident cache instead of each worker keeping its own copy. It complements the [shared invalidation study](shared-invalidation-feasibility.md), which shared only change streams, and uses the multi-worker application context from [issue #197](https://github.com/alessio-locatelli/client-query-cache/issues/197). Shared storage remains a research question; the supported managers keep process-local caches.

**Recommendation:** defer a supported shared-cache mode. The prototype halved group memory at eight workers and served hits faster than direct MongoDB reads, but at the registered fixed load it raised request P99 latency by 30–69% and total CPU per request by 63–82% compared with independent managers. Both conditions are registered promotion criteria, so screening stopped the candidate. Profiling attributes the excess to per-request owner work rather than to payload transfer, so neither registered payload-store alternative could remove it.

## What was measured

The [version 4 registration](../../../reports/shared-worker-cache/v4/registration.md) and its frozen [configuration](../../../reports/shared-worker-cache/v4/config.json) define the workload, paths, estimands and gate. In short:

- **Direct** workers read MongoDB with primary read preference and majority read concern.
- **Independent** workers each own a supported `CacheManager` with a 96 MiB budget and their own change stream.
- **Shared** workers attach to one application-owned research owner process that holds a single `CacheCore`, a 96 MiB group budget and one change stream. Workers keep their own clients for native reads, send coarse select and admission requests over a private Unix-domain socket, and decode stored BSON locally. The prototype supports `_id` `find_one` and sorted `find` cursors through research adapters around the supported facades; other reads execute natively.

Each worker primes the full 16,384-document catalogue (68.3 MiB of encoded entries) before every window, then issues an open-loop schedule at four requests in flight per worker. Latency is measured from each request's scheduled issue time, so queueing counts. Every window recreates the data, processes and caches; path order is counterbalanced across blocks.

## Calibration

Baseline-only calibration on the test host froze 1,267 reads/s for the primary workload, 1,000 reads/s for cold misses and 286 reads/s for the large-document and sorted-find sensitivity profiles. The primary rate halved once because one-worker direct reads could not complete 99% of 2,534 reads/s inside the window. All 294 calibration windows were healthy; the [registration](../../../reports/shared-worker-cache/v4/registration.md#calibration-result) records the probe ranges.

Three earlier registrations ended before freezing because calibration windows failed setup checks, not because of overload. Version 1 lost a container-statistics connection and then saw a late harness write in a host-saturating probe; versions 2 and 3 saw late writes because the harness issued writes sequentially, so one slow MongoDB update delayed the rest. Version 4 dispatches writes on schedule through a small writer pool. The [registration history](../../../reports/shared-worker-cache/v4/registration.md#registration-history) keeps each outcome.

## Screening result

Screening compared the three paths at one, four and eight workers in synchronous and asyncio groups, with six blocks of 30-second windows. Its futility rule stops a candidate when any point estimate at four or eight workers violates a promotion criterion. All 108 windows were healthy and completed every scheduled read.

| Cell         | Group PSS, shared ÷ independent | Hit P95, shared ÷ direct | Request P99, shared vs independent | CPU per request, shared vs independent |
| ------------ | ------------------------------: | -----------------------: | ---------------------------------- | -------------------------------------- |
| Sync, 4      |                            0.61 |                     0.43 | 0.92 vs 0.55 ms (×1.69)            | 425 vs 257 µs (×1.65)                  |
| Asyncio, 4   |                            0.60 |                     0.60 | 1.94 vs 1.45 ms (×1.34)            | 541 vs 297 µs (×1.82)                  |
| Asyncio, 8   |                            0.48 |                     0.55 | 1.98 vs 1.52 ms (×1.31)            | 599 vs 350 µs (×1.71)                  |
| Sync, 8 (\*) |                            0.48 |                     0.40 | 0.90 vs 0.54 ms (×1.67)            | 457 vs 280 µs (×1.63)                  |

Values are means of the six block statistics; ratios are the registered ratio-of-means estimands. CPU per request sums worker, owner and MongoDB CPU over the window and drain. At eight workers the shared group held 477 MiB PSS against 1,003 MiB for independent managers, and MongoDB traffic fell to a third because one stream replaced eight.

The registered gate allows request P99 at most 1.25 times independent and total CPU per request at most 1.10 times independent. Both failed in every cell, so the verdict is **stop**. The other screened criteria passed: group memory (limit 0.75), peak memory and application-plus-MongoDB memory (limit 1.10), hit P95 and P99 against direct reads (limits 0.75 and 1.0), the 1 ms request-P99 delta (observed 0.37–0.49 ms) and MongoDB traffic. No confirmation, capacity, active, cold, sensitivity or fault phase was collected, as the futility rule requires.

(\*) The registered eight-worker synchronous shared windows were invalid. Each open loop started new executor threads, and the prototype's synchronous endpoint kept every finished thread's connection open, so a quarter of the requests found the owner's 64-connection limit exhausted and fell back to MongoDB. That cell showed ×4.13 request P99, ×2.80 CPU and 262 times the MongoDB traffic. The row above comes from a labelled exploratory rerun after the fix; it is not decision evidence, and the verdict rests on the three unaffected cells.

## Bottleneck attribution

At 1,267 reads/s the owner was busy 15–17% of the time and used 16–19% of one core, about 120–135 µs of owner time per read, whatever the worker count. Window profiles of the owner at four and eight asyncio workers place most of that time in per-request work: frame parsing and dispatch, the availability, progress and epoch checks, and the core lookup with its lock and guard context managers. Encoding the 4 KiB reply and sending it each accounted for less than 3% of profiled owner busy time. Workers additionally pay the socket round trip and request encoding on top of the facade work they already do for local hits.

The registered trigger for a second candidate requires payload-proportional work to explain at least half of the shared path's excess. It does not come close, and both registered alternatives, an LMDB payload store or coordinator-managed shared-memory payloads, would keep the owner round trip that dominates the excess. No second prototype was built. A design that avoided the round trip would need workers to evaluate validity locally from shared state, which is the second cache algorithm the design rules out.

The owner serializes every lookup in one Python thread. At about 130 µs per read, one owner would saturate near 7,500 reads/s, while independent managers sustained 150,000 hot reads/s at eight workers in calibration probes. This is an extrapolation from utilization, not a measured capacity result, but it indicates that the capacity criterion would also be at risk.

## Supporting diagnostics

These were exploratory and excluded from the gate.

- **Transport.** Sequential 4 KiB hits took 39 µs median through the socket owner and 23 µs through a coarse `multiprocessing` manager proxy that skips every owner check and uses pickle. The asyncio event-loop adapter cost 42 µs and 23 µs of caller CPU per hit against 66 µs and 41 µs for a thread-executor wrapper.
- **Observer overhead.** Sampling group PSS every 200 ms instead of every 5 s added 1.1–1.4 CPU seconds per 30-second window to the harness, with no measurable change in worker request P99, CPU per request or group PSS at four asyncio workers.
- **Launch and recycling.** One explicit owner served recycled Gunicorn pre-fork and Uvicorn spawned workers: eight successive workers per server attached with new clients, hit entries admitted by earlier workers and saw one owner incarnation. Starting the owner with `multiprocessing` in Gunicorn's master leaves it registered as a child in each forked worker, which logs an assertion when a worker exits.

## Safety evidence

`tests/shared_cache/` exercises the design's failure table against real owner and worker processes: owner restart and duplicate startup, owner pauses past the RPC deadline, a stalled watch with live RPC, a transparently resumed stream, lost resume history, a killed worker holding a capture, a replacement worker, slow and malformed peers, owner exit during stream activation, cancelled asyncio selections, inherited attachments, capture bounds and processed invalidations. All pass. They show that the prototype's fencing works as designed; the registered timed fault phase did not run, so the study makes no readiness-duration claim.

## Limitations

The measurements cover one host with eight logical CPUs (Intel Core i3-13100), Linux 7.2.9, Python 3.14.6, PyMongo 4.18.2, and MongoDB 8.0.4 in a single-member replica set limited to two CPUs and 2 GiB. The host was not dedicated: an unrelated video service and a browser used roughly 0.3 CPU between them. The workload is one catalogue collection with 4 KiB documents read by `_id` at a fixed load chosen so that every baseline stays unsaturated. A faster owner implementation, another language runtime or a workload with much larger documents could change the balance, but would need a new registration. The results say nothing about sharded clusters or multiple hosts.

## Reproduce

Use the [contributor environment](../../../CONTRIBUTING.md) and configure the container bridge:

```bash
source scripts/testcontainers-bridge.sh
uv run -- python -m benchmarks.stream_cost.shared_cache.run --smoke --output benchmark-reports/shared-worker-cache/smoke.json
uv run -- python -m benchmarks.stream_cost.shared_cache.run --phase screening --output benchmark-reports/shared-worker-cache/screening.json
uv run -- python -m benchmarks.stream_cost.shared_cache.analysis benchmark-reports/shared-worker-cache/screening.json --config reports/shared-worker-cache/v4/config.json --phase screening --blocks 6
```

The smoke run takes a few minutes and cannot support the gate. Screening takes about two and a half hours; a run interrupted by the host can continue with `--resume <earlier report>`. Calibration, diagnostics, profiling and the launch smoke are listed in the [registration](../../../reports/shared-worker-cache/v4/registration.md#reproduction). The registered screening ran at revision `5ceb0c3a981572c1f465ba113c58d60d4e935bb1` with configuration SHA-256 `43156e75cd664bb4fd97fbb891f21139b1ac0d4cd0a436de8673cfd63b535f78`; the exploratory eight-worker rerun ran at `6579f36` and the diagnostics at `be9c522` and `8407b03`. Raw reports remain untracked.
