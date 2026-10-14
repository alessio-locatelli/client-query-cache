# Version 8 results

**Decision: defer.** The complete study passes hot, active, capacity and timed fault checks, but cold-miss P99 does not pass the acceptance bound in three of four required comparisons. [Issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272) remains open. The [registration](registration.md) defines the queue candidate, required phases and unchanged acceptance bounds.

## Calibration

Fresh baseline-only calibration ran at clean revision `63b5ef59be0649176b58892eceb7554bc88a6828` with pending configuration SHA-256 `d2a24369b05dff8efe0dccab964779bf7142e2b0b149fd1fb59df8a3f25a76a7`. All 114 probe and 180 validation windows were healthy, with no read exceptions.

| Family      | Frozen reads/s |            Window duration |
| ----------- | -------------: | -------------------------: |
| Primary     |          1,006 |      30 s hot; 60 s active |
| Cold        |          1,000 | 10 s for 10,000 identities |
| Sensitivity |            319 |                       32 s |

The first primary-rate attempt at 2,012 reads/s failed qualification in all three one-worker synchronous direct-read windows: two overflowed the bounded request queue, and one retained a growing backlog at the end of the window. All 66 windows from that attempt remain in the calibration report. The registered halving rule selected 1,006 reads/s, which passed all 66 primary validation windows. Cold and sensitivity passed their first selected rates, with 24 validation windows each. Calibration is excluded from promotion inference.

The frozen performance configuration has SHA-256 `7cfa0e9538845ec225063c923905b3bbb1d888ca8d22612a19f4b126b18abeb4`. The separate fault configuration has SHA-256 `16d954a03c87bfb583918d38b24facb6a1e2af61e03afb0a79f043483b620ab5`. Raw calibration output remains untracked; reproduce it with the commands in the [registration](registration.md#reproduce).

## Complete candidate evidence

All candidate phases used clean revision `7e933c7f39f66294a95bbe5511bb10a3711d1c8b` with the configuration digests above. The smoke run at the calibration revision had nine healthy windows and exercised native admission in both active and cold workloads. Smoke is an instrumentation check and does not support acceptance.

| Phase        | Windows | Outcome                                                   |
| ------------ | ------: | --------------------------------------------------------- |
| Screening    |     108 | Continue; all 36 comparisons pass                         |
| Confirmation |     144 | All 36 comparisons pass                                   |
| Capacity     |     162 | All 24 comparisons pass; every registered window retained |
| Active       |     180 | All 32 comparisons pass                                   |
| Cold         |     144 | Defer; three P99 comparisons do not pass                  |
| Sensitivity  |      36 | Large documents pass; sorted finds defer                  |
| Timed faults |      75 | All fifteen cases pass in all five repetitions            |

Every performance window was healthy, with no read exceptions or completion failures. No capacity windows were excluded or replaced. The maximum applicable fault detection, readiness, first-hit and rewarming durations were 3.267, 0.232, 0.243 and 0.298 seconds respectively. Detection for silent faults includes the registered 3-second progress expiry.

### Cold misses

The table reports additive latency against direct reads, in milliseconds. Each comparison has twelve paired blocks. The registered bootstrap, second-seed and leave-one-out checks apply; the limit is 1.000 ms.

| Model   | Workers | P95 point | P95 upper | P99 point | P99 upper | P99 outcome |
| ------- | ------: | --------: | --------: | --------: | --------: | ----------- |
| Asyncio |       4 |     0.497 |     0.541 |     0.790 |     1.099 | Unstable    |
| Asyncio |       8 |     0.631 |     0.682 |     0.947 |     1.143 | Fail        |
| Sync    |       4 |     0.389 |     0.437 |     0.618 |     0.734 | Pass        |
| Sync    |       8 |     0.481 |     0.516 |     0.838 |     0.994 | Unstable    |

All P95 comparisons pass. Only four-worker synchronous P99 passes all registered checks. The eight-worker synchronous upper bound falls below the limit in the primary bootstrap, but its stability checks disagree; it cannot qualify as a pass. Passing point estimates and other phases cannot override these outcomes.

The measured queue carried all 10,000 admissions per asyncio cold window. Synchronous windows carried 9,984 at four workers and 9,968 at eight; remaining misses used the existing data-channel fallback. Queue use therefore does not establish that its worker overhead is negligible.

### Sensitivity

The 64 KiB document profile passes every comparison. Sorted sixteen-document finds fail memory, CPU and request P99 in both models. For asyncio and synchronous reads respectively, upper ratios are 1.029 and 1.054 for memory, 1.408 and 1.575 for CPU, and 1.295 and 1.439 for request P99. Sorted-find optimization is outside issue #272; this evidence prevents a general shared-cache promotion claim.

## Remaining cost

Across the twelve unprofiled cold blocks, mean owner CPU ranges from 190 to 215 microseconds per shared miss across the four required cells. Workers use 146–175 microseconds more per miss than direct reads. Version 7's corresponding cell means were 245–298 and 78–126 microseconds. These are separate studies, not a paired estimate of the queue's effect: lower observed owner cost does not demonstrate lower total cost or a passing miss tail.

A separate one-block, eight-worker asyncio cProfile diagnostic at the candidate revision completed all three paths with healthy windows. The shared workers' profile identifies identity-key construction, admission construction and frame encoding, with native queue publication also visible. The owner still enters about 22 context managers per admission and performs authoritative core insertion in Python. Profile times include instrumentation overhead; blocking syscall time is wall time, not CPU. Further optimization and a fresh registered study are required under issue #272.

Reproduce the diagnostic with a disposable copy of the frozen configuration, `phases.cold.blocks` set to one, `SHARED_CACHE_PROFILE_DIRECTORY` set to an untracked directory, and `python -m benchmarks.stream_cost.shared_cache.run --phase cold --only async:8 --config <diagnostic-config> --output <diagnostic-report>`. It is exploratory and excluded from the gate.

Raw performance, fault, calibration and profile outputs remain untracked. The [registration](registration.md#reproduce) gives the complete reproduction commands. [Issue #278](https://github.com/alessio-locatelli/client-query-cache/issues/278) investigates benchmark runtime and statistical precision; it changes none of this study's registered rules or conclusions.
