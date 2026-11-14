# Native admission queue saturation

This assessment addresses [issue #289](https://github.com/alessio-locatelli/client-query-cache/issues/289). Concurrent large misses can lose admissions with public queue sizing. Recovery-triggered socket fallback improves subsequent warming, with an approved cold-read latency cost for this workload. These measurements do not establish a universal latency improvement or a guaranteed loss-rate bound.

## Workload and evidence

The [runner](../../../research/admission_saturation/run.py) reuses the isolated MongoDB replica-set infrastructure and retains each worker group across passes. Eight spawned processes each use four synchronous reader threads. Each worker reads 256 distinct documents in cold, revisit and recovery passes, with 500 ms settling after each pass. Payloads contain 4,096 or 65,536 bytes; BSON documents and admission frames are larger. The cache budget is 256 MiB and the arena is 320 MiB, sufficient for the 2,048-document set. MongoDB has two CPUs and a 2 GiB memory limit.

The public queue is 1,114,112 bytes per worker. Deliberately reduced queues contain twice the payload bytes, enough for one complete frame. Paused windows suspend the disposable owner during the cold pass, then resume it before settling. These two scenarios are fault injections. Normal windows use public sizing and leave the owner running; their synchronized closed-loop bursts are stress evidence, not a production traffic estimate. A preconnected control opens all reader-thread data sockets before measurement.

The main comparison measures recovery-triggered fallback at
`8f5e854b87ac91d18104063056becbb8afd5c8d6` against baseline
`ae422f36500fafd20b37707e4a1e2d4914c775ab`. The baseline uses three repetitions
per scenario; fallback uses six normal-capacity repetitions per payload and three
paused-owner repetitions. A separate six-window 64 KiB cohort measures the
completed policy at `695bddedc8ec329bb0e9acb7c4b08f4696c6b4b3`, which also
preserves native admission when socket recovery fails. These are historical
Python-coordinated admission measurements; current shared ownership is native.
The cohorts use the same interpreter, dependencies and native binary, with no
concurrent validation load. They are descriptive, not paired measurements.

Loss rate is dropped sends divided by misses; hit rate is hits divided by all reads. The runner checks that successful sends plus dropped sends equal misses. Window P99s use individual read latencies. Owner CPU includes the pass and settling, measured with `psutil`; its 10 ms resolution limits small comparisons. Connected-control setup is excluded, while recovery-triggered setup is included. Reported medians summarize windows and ranges span repetitions. These short measurements carry no inferential confidence claim.

## Admission losses and warming

| Payload | Scenario     | Baseline cold losses | Fallback cold losses | Baseline revisit hits | Fallback revisit hits | Fallback third-pass hits |
| ------- | ------------ | -------------------: | -------------------: | --------------------: | --------------------: | -----------------------: |
| 4 KiB   | Normal       |                   0% |                   0% |                  100% |                  100% |                     100% |
| 4 KiB   | Paused owner |               10.94% |               10.94% |                89.06% |                89.06% |                     100% |
| 64 KiB  | Normal       |         59.28–63.92% |          8.20–17.87% |          36.08–40.72% |          82.13–91.80% |                     100% |
| 64 KiB  | Paused owner |               93.75% |               93.75% |                 6.25% |                 6.25% |                     100% |

Normal 64 KiB revisit and recovery passes have no further admission losses. All measured reads and eventual post-write checks complete, with no measured bypasses. Baseline third-pass hits are only 53.56–59.62% in normal 64 KiB windows and 26.71–41.50% after pausing the owner.

The reduced-queue baseline loses no 4 KiB admissions and loses 50.20–59.33% at 64 KiB. The preconnected baseline loses no admissions at either size and reaches 100% hits on both later passes. Thus the large-value problem occurs without reducing capacity or pausing the owner.

The completed-policy cohort at `695bdded` records 5.37–11.47% normal 64 KiB
cold losses and full third-pass hits. Its median cold duration is 329.8 ms and
owner CPU is 0.250 s, including settling. These samples and the main comparison
show that warming remains best effort: neither establishes a guaranteed loss
bound. Loss rates also change the amount of admission work, so lower losses do
not isolate per-read overhead.

The connection/resource policy is maintained in the
[shared implementation guide](../../../docs/development/shared-cache.md#admission-saturation).
In these cohorts normal 64 KiB windows opened 32 data sockets (four per worker)
and no further sockets on later passes. Normal 4 KiB windows needed none.
Together with eight control connections, the stressed topology used 40 slots.

## Warming and cold-latency trade-off

| Normal 64 KiB metric                                   | Baseline | Fallback |
| ------------------------------------------------------ | -------: | -------: |
| Median cold-pass duration                              |   248 ms |   315 ms |
| Median cold-pass P99                                   | 26.68 ms | 28.04 ms |
| Median cold-pass owner CPU, including settling         |   0.15 s |  0.235 s |
| Median summed application duration across three passes |   504 ms |   436 ms |
| Median summed owner CPU across three passes            |  0.280 s |  0.295 s |

The policy performs more admissions during the cold pass and shifts owner work into that pass. The warming/cold-latency tradeoff is approved for this workload; the small summed-duration and CPU differences are descriptive, not a general performance claim. Normal 4 KiB windows retain zero losses and full later-pass hits; median cold P99 is 19.51 ms versus 19.98 ms baseline. Paused-owner cold passes make no new connections; their median P99s are 18.27 ms at 4 KiB and 25.88 ms at 64 KiB.

## Recovery correctness constraint

The [shared implementation guide](../../../docs/development/shared-cache.md#admission-saturation)
defines capture preservation and owner-reply precedence during recovery. Resolve
hit/miss accounting after path selection so a recovered owner hit is not also
counted as a miss.

## Reproduce

Use the historical runner and runtime at the revisions named above. The
[recorded comparison procedure](https://github.com/alessio-locatelli/client-query-cache/blob/243cbfb790766e9ee25b3ecced1ffe83e96d083c/reports/shared-worker-cache/admission-saturation/results.md#correctness-and-reproduction)
defines how to load each historical variant with its matching native binary.
For fresh current-code stress measurements, use the contributor environment:

```bash
source scripts/testcontainers-bridge.sh
uv run python -m research.admission_saturation.run --modes default --repetitions 6 --output /tmp/agents/admission-normal.json
uv run python -m research.admission_saturation.run --modes paused --output /tmp/agents/admission-paused.json
```

The runner verifies identity/revision on each read and eventual post-write
visibility; it does not measure a strict lag guarantee. Paused-owner and reduced
queue cases are fault injections. Run versions sequentially using the same
interpreter and matching native binary, without concurrent tests or builds.
Raw output includes latencies, outcomes, CPU and connection counts. It stays
untracked; summaries cannot recover individual samples after disposal.
