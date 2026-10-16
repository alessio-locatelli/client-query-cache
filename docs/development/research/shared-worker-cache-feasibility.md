# Shared worker cache feasibility

This study asked whether a group of application worker processes on one host could share one resident cache instead of each worker keeping its own copy. It complements the [shared invalidation study](shared-invalidation-feasibility.md), which shared only change streams, and uses the multi-worker application context from [issue #197](https://github.com/alessio-locatelli/client-query-cache/issues/197). The [supported shared-cache guide](../../user/operations/shared-cache.md) defines the narrower 0.8.0 identity-read contract. This study records broader research protocols and their promotion gates.

**Research recommendation:** defer general shared-cache promotion under this study's broader gates. [Version 4](#screening-result) served every hit through a Python owner process, which cost too much CPU and latency. [Version 5](#version-5-local-hits-from-a-shared-index) serves hits from read-only shared memory that the owner publishes. It halved group memory at eight workers while using 13–32% less CPU per request and having a lower request P99 than independent managers, with or without writes. [Version 7](#local-miss-capture-version-7) repeats the complete study with locally captured misses; its eight-worker miss tail still fails the acceptance bound. [Version 6](#timed-fault-trials-version-6) reports separate scripted fault trials.

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

The registered trigger for a second candidate requires payload-proportional work to explain at least half of the shared path's excess. It does not come close, and both registered alternatives, an LMDB payload store or coordinator-managed shared-memory payloads, would keep the owner round trip that dominates the excess. No second prototype was built. A design that avoided the round trip would need workers to evaluate validity locally from shared state, which is the second cache algorithm the design rules out. [Issue #229](https://github.com/alessio-locatelli/client-query-cache/issues/229) tracks reducing the overhead through such a design change or a native implementation of the hot path.

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

## Version 5: local hits from a shared index

[Issue #229](https://github.com/alessio-locatelli/client-query-cache/issues/229) asked for a design that removes the per-hit owner round trip. The [version 5 registration](../../../reports/shared-worker-cache/v5/registration.md) and its frozen [configuration](../../../reports/shared-worker-cache/v5/config.json) reuse version 4's workload, phases, estimands and gate, and compare direct reads and independent managers with one candidate, `shared-index`:

- The owner keeps version 4's single `CacheCore`, change stream and 96 MiB group budget. It stores each admitted payload once, in a shared arena, and publishes every resident `_id` entry with its validity words into a sealed, read-only shared index. A Rust extension built with PyO3 and maturin (`native/shared-index/`) implements the index.
- A worker serves an `_id` `find_one` from the index when its attachment is live, the owner incarnation matches, the database is available, the published upstream progress is under 3 seconds old and the namespace epoch matches. Otherwise it falls back to version 4's owner request. Misses, admissions, sorted finds and other reads keep version 4's paths.

### Cost floors and choice

Before any candidate was built, exploratory floors timed one minimal 4 KiB hit per mechanism. A shared-index lookup cost 5.8–6.9 µs of CPU, against 10.8–12.4 µs for a `CacheCore` hit in an independent manager. A native echo owner over a Unix-domain socket cost 14.3–24.8 µs. Both families were eligible under the registered 12.8 µs margin, and the registered order built the shared index first. The [registration](../../../reports/shared-worker-cache/v5/registration.md#candidate-selection) lists every floor. The native-owner family was not built, because the shared index failed no safety scenario or memory criterion.

### Calibration

Baseline calibration froze 976 reads/s for the primary and cold workloads and 319 reads/s for sensitivity. All 294 windows were healthy. The primary rate halved once, because one-worker synchronous direct reads completed only 95.8–97.0% of 1,953 reads/s inside the window. That rate is below version 4's 1,267 reads/s, because direct reads ran slower on the test host. Version 5 compares paths only within its own registration.

### Results

All 774 registered windows were healthy, and every scheduled read completed. Ratios are the registered ratio-of-means estimands with the upper end of the 95% paired-block bootstrap interval in brackets. Deltas are in milliseconds.

**Hot reads (confirmation, 12 blocks, 30-second windows): pass.**

| Cell       | Group PSS, ÷ independent | Hit P95, ÷ direct | Request P99, ÷ independent | CPU per request, ÷ independent |
| ---------- | -----------------------: | ----------------: | -------------------------: | -----------------------------: |
| Sync, 4    |            0.663 [0.664] |     0.248 [0.261] |              0.823 [0.860] |   0.843 [0.872]: 254 vs 301 µs |
| Sync, 8    |            0.513 [0.513] |     0.224 [0.251] |              0.734 [0.928] |   0.871 [0.907]: 278 vs 320 µs |
| Asyncio, 4 |            0.664 [0.664] |     0.445 [0.466] |              0.928 [0.946] |   0.835 [0.864]: 289 vs 346 µs |
| Asyncio, 8 |            0.513 [0.513] |     0.421 [0.439] |              0.920 [0.939] |   0.798 [0.845]: 331 vs 415 µs |

At eight workers the shared-index group held 499 MiB PSS against 973 MiB for independent managers. Peak memory, application-plus-MongoDB memory, hit P99, the 1 ms request-P99 delta and MongoDB traffic (0.33–0.46 of independent) also passed. Screening's six blocks gave the same picture.

**Reads with writes (active, 12 blocks, 200 updates per 60-second window): pass.** CPU per request was 0.68–0.82 of independent [upper ends 0.75–0.90]. Request P99 was 0.58–0.97 [0.66–1.06], including both models of the mixed group. The invalidation lag P95 was about 11 ms [at most 18.5 ms after clock expansion], within 7 ms of independent managers.

**Capacity (closed loop, 3 windows per point): fails in one window.** At four and eight workers the shared index sustained 1.23–1.48 times independent throughput and 7.3–20 times direct in every window except one. In the first eight-worker synchronous window at 16 requests in flight, it reached 127,000 reads/s, 0.84 of independent; its other two windows reached 219,000–220,000 reads/s, 1.44 of independent. In that window the workers and owner together received about half the CPU time of the other two windows, which suggests interference on the shared host. An exploratory rerun of that point gave 1.44 in every window. The registered rule counts every window, so capacity fails, and the rerun is not decision evidence.

**Cold misses (12 blocks, 10,000 distinct identities): fail.** The miss P99 delta to direct reads was 1.39–2.31 ms [1.55–2.49 ms] against the registered 1 ms. The miss P95 delta was 0.82–1.37 ms [0.85–1.42 ms], with only the four-worker synchronous cell within the limit. For comparison, independent managers' misses were 0.7–0.9 ms slower than direct reads at P99.

**Sensitivity (descriptive, 3 blocks at 8 workers).** With 64 KiB documents (`large`), every criterion passed, with group PSS at 0.52 of independent. Sorted finds (`find16`) are served through the owner as in version 4. They used 1.39–1.40 times independent CPU per request, had 1.28–1.41 times its request P99 and used 3–5% more group memory than independent managers, because their working set of about 4.3 MiB saves less memory than the owner process costs.

**Fault phase: not run.** The registration lists a timed fault phase with readiness within 5 seconds. Its frozen configuration carries no per-case timing applicability. [Issue #273](https://github.com/alessio-locatelli/client-query-cache/issues/273) is addressed by the separate version 6 registration below.

**Verdict: defer.** Hot reads, writes and memory pass every registered bound. Miss latency fails, capacity fails in one window and the fault evidence is missing. Under the [outcome handling](../../../openspec/changes/archive/2026-10-13-reduce-shared-cache-overhead/design.md#outcome-handling) for a deferred candidate whose memory, safety and fixed-load criteria pass, the extension stays in the repository, and a follow-up registration must repeat every phase, including capacity.

### Bottleneck

Hits no longer reach the owner. In hot windows, the owner spent about 12 µs of CPU per request on its sweep, progress publication and hit-ring recency touches. Misses still take version 4's path: a local miss, a select request to the Python owner, a native read and an admission message. At 976 misses/s the owner spent 283–338 µs of CPU per miss and was busy 25–30% of the time. An exploratory profile of the four-worker asyncio cold window places most of that in `CacheCore` admission and its lock and guard sections, and in request framing and dispatch. Waiting behind that single Python thread lengthens the miss tail. [Issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272) tracks reducing it. At peak hit rates the recency touches that the owner drains from the hit rings become visible: at 220,000 reads/s the owner used about 11 CPU seconds per 15-second window, and in the starved capacity window it dropped 128,000 touches. A full ring drops touches without blocking reads.

### Safety evidence

Before any timing, `cargo test` and `loom` model tests checked the version protocol and reclamation. A Hypothesis state machine checked published state against the authoritative `CacheCore`, and `tests/shared_cache/` exercised the shared index against real owner and worker processes: a killed owner stops local hits within 100 ms, a paused owner or stalled watch stops them by the 3-second expiry, a replacement owner's index is never confused with the old one, reads racing eviction churn in three processes only return published payloads, and workers cannot write the index through their descriptor, a writable mapping, `mprotect` or a `/proc` reopen. All pass.

### Limits

A paused owner that stays alive keeps entries servable for up to the 3-second progress expiry. That equals version 4's registered bound for silent faults but is weaker than version 4's 100 ms RPC deadline, and a supported mode would have to decide whether it is acceptable. The measurements ran on x86-64 only; evidence for weakly ordered CPUs such as ARM is limited to the `loom` models. The index uses Linux `memfd` seals. The host, an Intel Core i3-13100 with eight logical CPUs, ran Linux 7.2.9, CPython 3.14.7, PyMongo 4.18.2 and MongoDB 9.0.2 in a single-member replica set limited to two CPUs and 2 GiB. It was not dedicated, so eight-worker closed-loop windows are sensitive to other load.

### Reproduce version 5

Use the [contributor environment](../../../CONTRIBUTING.md), which builds the extension from the committed sources and lockfiles, and configure the container bridge:

```bash
source scripts/testcontainers-bridge.sh
uv run -- python -m benchmarks.stream_cost.shared_cache.run --phase confirmation --config reports/shared-worker-cache/v5/config.json --output benchmark-reports/shared-worker-cache/v5-confirmation.json
uv run -- python -m benchmarks.stream_cost.shared_cache.analysis benchmark-reports/shared-worker-cache/v5-confirmation.json --config reports/shared-worker-cache/v5/config.json --phase confirmation --blocks 12
```

The other phases use the same commands with their names and block counts: `screening` 6, `capacity` 3, `active` 12, `cold` 12 and `sensitivity` 3. Each takes one to five hours, and an interrupted run continues with `--resume <earlier report>`. The registration lists the smoke, calibration, floor and safety commands. Screening, confirmation and capacity ran at revision `e1986642ac04fd6658d5e2181d82045a1921a47a`, active at `4363970a4a6d7dcabf7c2aa3d860345252c74a18`, and cold and sensitivity at `c9bf928334251ecc9f0fc1798c0227bd7dd345a5`, all with configuration SHA-256 `57f4fcce3a96b6a04d0d0020f270411875806971126ecb2298bdc80e49df7580`. The extension was built by rustc 1.95.0 and maturin 1.15.0 with PyO3 0.29.3 as one `cp314-abi3` wheel. The exploratory capacity rerun used `--only sync:8`, and the profile used `python -m benchmarks.stream_cost.shared_cache.diagnostics --config reports/shared-worker-cache/v5/config.json --profile cold 4 async`. Raw reports remain untracked.

## Timed fault trials: version 6

The [version 6 registration](../../../reports/shared-worker-cache/v6/registration.md) runs all fifteen shared-cache cases with two synchronous and two asyncio workers. Its scripted 64-document hot set measures fault transitions separately from version 5's steady-state workload. The registration gives the reproduction commands and defines observation delays, applicability and safety checks. A successful native read alone does not establish cache readiness, and a passing fault phase cannot override version 5's failed miss-latency or capacity criteria.

All 75 registered repetitions passed with independent first-hit safety checks. The [results record](../../../reports/shared-worker-cache/v6/results.md) gives the measured revision, per-case timings, traffic preparation measurements and interpretation limits.

## Local miss capture: version 7

The [complete version 7 study](../../../reports/shared-worker-cache/v7/results.md) removes owner selection before eligible `_id` misses. Hot, active, capacity and timed fault checks pass, with every capacity window retained. Cold-miss P95 passes at four and eight workers in both models, and P99 passes at four. Eight-worker P99 upper deltas are 1.056 ms for asyncio and 1.134 ms for synchronous reads, exceeding the 1 ms limit. The study therefore defers. The report records the unchanged inference rules, source revisions, sensitivity limits and profiles.

[Issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272) remains open.

## Native admission queue: version 8

The [complete version 8 study](../../../reports/shared-worker-cache/v8/results.md) adds a bounded native queue for encoded admissions. Hot, active, capacity and timed fault checks pass, but cold-miss P99 does not pass in three of four required comparisons. Observed owner CPU is lower than in version 7 while worker CPU is higher; these separate studies do not establish a causal speedup. The report records every phase, stability failures and an exploratory profile. The candidate remains deferred under [issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272).

## Admission-cost continuation: version 10

The [version 10 registration](../../../reports/shared-worker-cache/v10/registration.md) applies the validated version 9 acquisition protocol to the current public library and records a fresh baseline environment. Its [development diagnostics](../../../reports/shared-worker-cache/v10/development.md) identify copying and guard costs. All 38 baseline and 144 cold windows complete healthily, but [cold P99 fails or is unstable in all four comparisons](../../../reports/shared-worker-cache/v10/results.md). The registered cold-first rule stops the study before the remaining phases.

The [version 11 study](../../../reports/shared-worker-cache/v11/results.md) tests shorter admission polling while preserving maintenance cadence, workloads and gates. One cold P99 comparison passes; the remaining three fail or are unstable. The [version 12 study](../../../reports/shared-worker-cache/v12/results.md) adds scalar fast paths and matches the byte relay's TCP delivery policy to PyMongo. Both four-worker P99 comparisons pass, while eight-worker async remains unstable and sync fails. Its stopping rule ends the study before the remaining phases; issue #272 remains open.

The [version 13 results](../../../reports/shared-worker-cache/v13/results.md) pass every cold bound after native relay I/O and allocation reductions, but leave one hot comparison unstable. The study is incomplete. The [version 14 registration](../../../reports/shared-worker-cache/v14/registration.md) removes repeated classification for default integer identity reads, retains the observer and all cache authorities, and requires fresh qualification and every acceptance phase.
