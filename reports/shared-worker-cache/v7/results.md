# Version 7 results

**Decision: defer.** The complete study passes the hot, active, capacity and timed fault gates, but eight-worker cold-miss P99 comparisons do not pass the 1 ms upper-bound limit. Issue #272 remains open. The [registration](registration.md) defines the required phases, inference and acceptance bounds.

## Calibration

Fresh baseline-only calibration ran at clean revision `5acd958854e31e17c04d2df629fab06c5c6769f7` with pending configuration SHA-256 `06f7e1adc2ac0707a3469c3e03145ccd1eae7458131b178272518affe7347fee`. All 114 probe and 180 validation windows were healthy, with no read exceptions.

| Family      | Frozen reads/s |            Window duration |
| ----------- | -------------: | -------------------------: |
| Primary     |          1,020 |      30 s hot; 60 s active |
| Cold        |          1,000 | 10 s for 10,000 identities |
| Sensitivity |            372 |                       30 s |

The first primary-rate attempt at 2,040 reads/s failed qualification in all three one-worker synchronous direct-read windows. One missed the completion threshold; two failed the bounded-queue criterion. These windows remain in the calibration report. The registered halving rule selected 1,020 reads/s, which passed every primary validation window. Cold and sensitivity passed their first selected rates. Calibration is excluded from promotion inference.

The owner transport recovery fix changes neither baseline path. The frozen performance configuration has SHA-256 `0b74334c1c7962a8d8bb15af8cce3798fd0b8a4426c44b404b3eb6df261d14b7`. The measured candidate revision and outcomes follow below. Raw calibration output remains untracked; reproduce it with the commands in the registration.

## Complete candidate evidence

All candidate phases used clean revision `ef8c3702ffa7b8cec3af905f8856c72878ccefd9`. The performance configuration digest is recorded above; the separate fault configuration has SHA-256 `ca0824f96b7ec1234818b8ef025c1b35ffa0ce4aa63b5177550df5c9c80f4bce`.

| Phase        | Windows | Outcome                                                   |
| ------------ | ------: | --------------------------------------------------------- |
| Smoke        |       9 | All healthy                                               |
| Screening    |     108 | Continue; all 36 comparisons pass                         |
| Confirmation |     144 | All 36 comparisons pass                                   |
| Capacity     |     162 | All 24 comparisons pass; every registered window retained |
| Active       |     180 | All 32 comparisons pass                                   |
| Cold         |     144 | Defer; eight-worker P99 does not pass                     |
| Sensitivity  |      36 | Large documents pass; sorted finds defer                  |
| Timed faults |      75 | All fifteen cases pass in all five repetitions            |

Every performance window was healthy, with no read exceptions or completion failures. No capacity windows were excluded or replaced. The fault run at the measured revision supersedes the supplemental run at `5acd958`; its maximum applicable detection, readiness, first-hit and rewarming durations were 3.316, 0.235, 0.236 and 0.277 seconds respectively. Detection for silent faults includes the registered 3-second progress expiry.

### Cold misses

The table reports additive latency against direct reads, in milliseconds. Each comparison has twelve paired blocks. The existing bootstrap, seed stability and leave-one-out rules apply; the limit is 1.000 ms.

| Model   | Workers | P95 point | P95 upper | P99 point | P99 upper | P99 outcome |
| ------- | ------: | --------: | --------: | --------: | --------: | ----------- |
| Asyncio |       4 |     0.474 |     0.518 |     0.801 |     0.950 | Pass        |
| Asyncio |       8 |     0.651 |     0.689 |     0.923 |     1.056 | Unstable    |
| Sync    |       4 |     0.433 |     0.458 |     0.827 |     0.934 | Pass        |
| Sync    |       8 |     0.479 |     0.513 |     1.000 |     1.134 | Fail        |

All P95 comparisons and both four-worker P99 comparisons pass. At eight workers the asyncio P99 upper bound exceeds the limit and the registered stability checks disagree; the synchronous P99 comparison fails. Passing point estimates or other phases cannot override these outcomes.

### Sensitivity

The 64 KiB document profile passes every comparison. Sorted sixteen-document finds fail the group-memory and CPU criteria in both models, and request P99 in the synchronous model. Their upper ratios are 1.031 and 1.053 for memory, 1.444 and 1.423 for CPU, and 1.374 for synchronous request P99. Sorted-find optimization is outside issue #272; this evidence prevents a general shared-cache promotion claim.

## Bottleneck profile

Across the twelve unprofiled cold blocks, the owner uses 245–298 microseconds of CPU per shared miss; workers use 79–126 microseconds more per miss than direct reads. A separate one-block, eight-worker asyncio cProfile diagnostic attributes visible worker cost to key construction, frame encoding and socket sends. The owner profile records about 22 context-manager constructions and ten namespace sections per admission. Core lock-order guards forbid holding a namespace lock through LRU insertion, so merging those sections requires a broader concurrency redesign.

The diagnostic used the measured revision with a disposable copy of the frozen configuration, `phases.cold.blocks` set to one, and `SHARED_CACHE_PROFILE_DIRECTORY` set to an untracked directory. Reproduce with `python -m benchmarks.stream_cost.shared_cache.run --phase cold --only async:8 --config <diagnostic-config> --output <diagnostic-report>`. It is exploratory and excluded from the gate. Blocking syscall timings in cProfile are wall time, not CPU measurements.

Raw performance, fault, calibration and profile outputs remain untracked. The [registration](registration.md#reproduce) gives the complete reproduction commands. [Version 8](../v8/registration.md) preregisters a queue candidate; it does not revise these results.
