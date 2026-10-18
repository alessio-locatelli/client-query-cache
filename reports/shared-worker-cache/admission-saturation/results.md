# Native admission queue saturation

This assessment addresses [issue #289](https://github.com/alessio-locatelli/client-query-cache/issues/289). Concurrent large misses can lose admissions with public queue sizing. Recovery-triggered socket fallback improves subsequent warming, with an approved cold-read latency cost for this workload. These measurements do not establish a universal latency improvement or a guaranteed loss-rate bound.

## Workload and evidence

The [runner](../../../research/admission_saturation/run.py) reuses the isolated MongoDB replica-set infrastructure and retains each worker group across passes. Eight spawned processes each use four synchronous reader threads. Each worker reads 256 distinct documents in cold, revisit and recovery passes, with 500 ms settling after each pass. Payloads contain 4,096 or 65,536 bytes; BSON documents and admission frames are larger. The cache budget is 256 MiB and the arena is 320 MiB, sufficient for the 2,048-document set. MongoDB has two CPUs and a 2 GiB memory limit.

The public queue is 1,114,112 bytes per worker. Deliberately reduced queues contain twice the payload bytes, enough for one complete frame. Paused windows suspend the disposable owner during the cold pass, then resume it before settling. These two scenarios are fault injections. Normal windows use public sizing and leave the owner running; their synchronized closed-loop bursts are stress evidence, not a production traffic estimate. A preconnected control opens all reader-thread data sockets before measurement.

The baseline is `ae422f36500fafd20b37707e4a1e2d4914c775ab` (`main`), with three repetitions per scenario. Final normal-capacity validation uses six repetitions per payload; paused-owner validation uses three. A focused recovery-policy comparison uses six windows of the previous PR version (`f7b357d1859f98e258fbe81bbf83cc74dd0560cb`) and six final-version windows at 64 KiB. Previous-policy controls bracketed an earlier bounded-policy iteration; the final generation-fenced windows were acquired subsequently. These are descriptive cohorts, not paired final-version measurements. No native source or build change occurs between variants. Pure-hit controls use the same interpreter, dependencies and copied native binary; source fingerprints verify the loaded variant.

Loss rate is dropped sends divided by misses; hit rate is hits divided by all reads. The runner checks that successful sends plus dropped sends equal misses. Window P99s use individual read latencies. Owner CPU includes the pass and settling, measured with `psutil`; its 10 ms resolution limits small comparisons. Connected-control setup is excluded, while recovery-triggered setup is included. Reported medians summarize windows and ranges span repetitions. These short measurements carry no inferential confidence claim.

## Admission losses and warming

| Payload | Scenario     | Baseline cold losses | Final cold losses | Baseline revisit hits | Final revisit hits | Final third-pass hits |
| ------- | ------------ | -------------------: | ----------------: | --------------------: | -----------------: | --------------------: |
| 4 KiB   | Normal       |                   0% |                0% |                  100% |               100% |                  100% |
| 4 KiB   | Paused owner |               10.94% |            10.94% |                89.06% |             89.06% |                  100% |
| 64 KiB  | Normal       |         59.28–63.92% |       8.20–17.87% |          36.08–40.72% |       82.13–91.80% |                  100% |
| 64 KiB  | Paused owner |               93.75% |            93.75% |                 6.25% |              6.25% |                  100% |

Normal 64 KiB revisit and recovery passes have no further admission losses. All measured reads and eventual post-write checks complete, with no measured bypasses. Baseline third-pass hits are only 53.56–59.62% in normal 64 KiB windows and 26.71–41.50% after pausing the owner.

The reduced-queue baseline loses no 4 KiB admissions and loses 50.20–59.33% at 64 KiB. The preconnected baseline loses no admissions at either size and reaches 100% hits on both later passes. Thus the large-value problem occurs without reducing capacity or pausing the owner.

The initial three-window candidate sample had 6.59–8.54% normal 64 KiB losses. Expanded controls show that **below 9% is not a stable bound**: the previous PR policy reaches 6.49–13.62%, overlapping the final policy's 8.20–17.87%. The final sample includes higher-loss windows; this remains best-effort warming, rather than a guaranteed admission rate. Both establish all data sockets and reach 100% third-pass hits. Median cold duration is 320.5 ms for the previous policy and 314.9 ms for the final policy; median cold owner CPU is 0.24 seconds for the previous policy and 0.235 seconds for the final policy. The focused comparison does not reproduce an additional cold-pass performance cost from bounding recovery state.

## Recovery state and connection bounds

A failed enqueue with no data socket records a native admission drop and marks the queue as awaiting capacity. The next successful enqueue completes that episode and increments `native_admission_recoveries` once. Further successes neither increment that diagnostic counter nor extend the recovery window. Policy state is separate from counters, so diagnostic resets cannot change it. Each drop advances a generation; a successful enqueue can complete only the generation sampled before that native operation. This prevents delayed callbacks from reopening recovery after a newer drop.

For 100 ms after recovery, disconnected identity misses may establish a data socket through existing owner selection. Expiry returns disconnected readers to queue-only admission. A new drop cancels the current window until capacity returns again. A queue that stays full causes no recovery-triggered connection attempts. Existing sockets remain available under their normal thread/manager lease lifecycle: closing them on timer expiry could interrupt requests and would recreate connections during recurring pressure. The policy does not retain an unlimited connection pool or permanently require new threads to connect.

Connection measurements count successful data-channel handshakes and inspect every reader thread's lease after each pass:

- Normal 4 KiB windows open no additional data sockets.
- Normal 64 KiB windows open exactly 32 additional sockets during the cold pass, one per reader thread, and none in either later pass.
- Paused windows open none while suspended, then 32 during revisit and none during recovery.

These workloads therefore need 40 steady-state owner connection slots after recovery: eight control connections plus 32 data sockets. Initial worker setup sockets are closed before measurement and are excluded from additional-connection counts. The configured default limit is 256; connection sizing guidance remains in the [deployment guide](../../../docs/user/operations/shared-cache.md#collection-names-and-capacity).

`test_recovery_at_owner_connection_capacity_preserves_native_reads` sets the owner limit to two, occupies both slots, and attempts recovery with eight concurrent readers in each endpoint model. Every MongoDB read succeeds, owner occupancy stays at two, and the owner retains no capture handles. Refusals are bounded by the concurrent attempts and use existing retry cooldowns. After recovery expires, the same occupied owner admits through the existing native queue without further connection failures. Full-queue tests exercise actual drop → drain → successful-enqueue transitions, quiet enqueue counter semantics, and both endpoint models; clock-controlled tests verify expiry without timing-dependent assertions.

## Latency costs and the third-pass investigation

| Normal 64 KiB metric                                   | Baseline | Final policy |
| ------------------------------------------------------ | -------: | -----------: |
| Median cold-pass duration                              |   248 ms |       315 ms |
| Median cold-pass P99                                   | 26.68 ms |     28.04 ms |
| Median cold-pass owner CPU, including settling         |   0.15 s |      0.235 s |
| Median summed application duration across three passes |   504 ms |       436 ms |
| Median summed owner CPU across three passes            |  0.280 s |      0.295 s |

The policy performs more admissions during the cold pass and shifts owner work into that pass. The warming/cold-latency tradeoff is approved for this workload; the small summed-duration and CPU differences are descriptive, not a general performance claim. Normal 4 KiB windows retain zero losses and full later-pass hits; median cold P99 is 19.51 ms versus 19.98 ms baseline. Paused-owner cold passes make no new connections; their median P99s are 18.27 ms at 4 KiB and 25.88 ms at 64 KiB. An immediate-reconnect candidate that incurred roughly 250 ms paused-owner P99 is rejected.

The initial third-pass P99 comparison was 7.14 ms baseline versus 15.49 ms candidate. It did not isolate hit performance: baseline windows had only 54–60% hits, while candidate windows had 100%. Repeated short per-read executor batches also produce widely separated tail regimes on `main`: window medians range from 0.122 to 16.504 ms, while individual batch P99s range from 0.060 to 20.487 ms. Final-policy third-pass P99s themselves range from 0.094 to 17.501 ms with 100% hits. A single short-window P99 is therefore insufficient to attribute a hit-path regression.

A second control assigns equal long chunks to all four threads, avoiding a separate executor future for each hit. Each process performs 4,096 hits per batch over its fully warmed 256-key set. Four windows per version, with five batches per window, retain 100% hits, zero bypasses and zero measured connection setup. Two baseline windows precede and two follow the candidate windows. The admission-recovery predicates are inside the failed-lookup branch; these all-hit reads do not execute them.

Across equal-chunk batches, P99 ranges are 0.071–0.393 ms in the first baseline group, 0.079–0.480 ms in the candidate group, and 0.075–0.241 ms in the second baseline group. Group medians are 0.187, 0.222 and 0.213 ms respectively. Window-median P99 ranges overlap: 0.181–0.264 ms for baseline and 0.165–0.252 ms for candidate. Read medians also overlap (38.06–38.25 versus 37.82–38.19 µs). These controls do not reproduce a consistent candidate-specific hit-path regression. They establish variation in the measured tail, without identifying a particular scheduling or runtime cause. The final generation-fencing change affects admission sends only; the measured all-hit selector is unchanged.

## Correctness and reproduction

The runner checks identity and revision on every read. After the passes and settling, it updates every measured document through MongoDB and requires every worker to observe revision 1 within ten seconds. This checks eventual invalidation and availability, not a stricter invalidation-latency guarantee or a write racing queued admission. Existing owner tests separately cover obsolete captures after writes/reset/unavailability, mutations during admission and progress-publication fencing. Queue operation-ordering and concurrent-frame tests remain unchanged. The recovery policy retains those core and publication paths.

From the repository root, use the existing native build procedure and acquire fresh output files:

```bash
source scripts/testcontainers-bridge.sh
mkdir -p /tmp/agents/admission-saturation
uv run python -m research.admission_saturation.run --modes default --repetitions 6 --output /tmp/agents/admission-saturation/normal.json
uv run python -m research.admission_saturation.run --modes paused --output /tmp/agents/admission-saturation/paused.json
```

The runner refuses to overwrite reports. To compare with `main` using the same interpreter and native binary, copy only the research driver and compiled extension into a disposable checkout:

```bash
(
  set -e
  source scripts/testcontainers-bridge.sh
  study_python=$(uv run python -c 'import sys; print(sys.executable)')
  study_native=$(uv run python -c 'from client_query_cache import _shared_index; print(_shared_index.__file__)')
  git worktree add --detach /tmp/agents/admission-saturation/baseline ae422f36500fafd20b37707e4a1e2d4914c775ab
  cp -r research/admission_saturation /tmp/agents/admission-saturation/baseline/research/
  cp "$study_native" /tmp/agents/admission-saturation/baseline/src/client_query_cache/
  (
    cd /tmp/agents/admission-saturation/baseline
    PYTHONPATH="$PWD/src:$PWD" "$study_python" -m research.admission_saturation.run --modes default --payloads 65536 --hot-passes 5 --repetitions 2 --output /tmp/agents/admission-saturation/baseline-hot-a.json
  )
  uv run python -m research.admission_saturation.run --modes default --payloads 65536 --hot-passes 5 --repetitions 4 --output /tmp/agents/admission-saturation/candidate-hot.json
  (
    cd /tmp/agents/admission-saturation/baseline
    PYTHONPATH="$PWD/src:$PWD" "$study_python" -m research.admission_saturation.run --modes default --payloads 65536 --hot-passes 5 --repetitions 2 --output /tmp/agents/admission-saturation/baseline-hot-b.json
  )
  rmw /tmp/agents/admission-saturation/baseline/research/admission_saturation
  git worktree remove /tmp/agents/admission-saturation/baseline
)
```

For the recovery-policy comparison, substitute `f7b357d1859f98e258fbe81bbf83cc74dd0560cb`, omit hot passes, and use three previous-policy windows before and three after six final-policy windows at 64 KiB. That revision already tracks the driver: replace the `rmw` cleanup with `git -C /tmp/agents/admission-saturation/baseline restore -- research/admission_saturation/run.py` before removing the worktree. Run variants sequentially without concurrent tests or benchmarks. Raw reports include individual latencies, counters, phase CPU, thread connection counts, source/native hashes and environment metadata. Keep them untracked. Temporary output permits current inspection; the summary and runner support fresh acquisition, not independent recomputation after raw output is lost.
