# Version 8 results

**Decision: incomplete.** Baseline calibration is complete; candidate measurements are pending. Issue #272 remains open. The [registration](registration.md) defines the queue candidate, required phases and unchanged acceptance bounds.

## Calibration

Fresh baseline-only calibration ran at clean revision `63b5ef59be0649176b58892eceb7554bc88a6828` with pending configuration SHA-256 `d2a24369b05dff8efe0dccab964779bf7142e2b0b149fd1fb59df8a3f25a76a7`. All 114 probe and 180 validation windows were healthy, with no read exceptions.

| Family      | Frozen reads/s |            Window duration |
| ----------- | -------------: | -------------------------: |
| Primary     |          1,006 |      30 s hot; 60 s active |
| Cold        |          1,000 | 10 s for 10,000 identities |
| Sensitivity |            319 |                       32 s |

The first primary-rate attempt at 2,012 reads/s failed qualification in all three one-worker synchronous direct-read windows: two overflowed the bounded request queue, and one retained a growing backlog at the end of the window. All 66 windows from that attempt remain in the calibration report. The registered halving rule selected 1,006 reads/s, which passed all 66 primary validation windows. Cold and sensitivity passed their first selected rates, with 24 validation windows each. Calibration is excluded from promotion inference.

The frozen performance configuration has SHA-256 `7cfa0e9538845ec225063c923905b3bbb1d888ca8d22612a19f4b126b18abeb4`. The separate fault configuration has SHA-256 `16d954a03c87bfb583918d38b24facb6a1e2af61e03afb0a79f043483b620ab5`. Raw calibration output remains untracked; reproduce it with the commands in the [registration](registration.md#reproduce).

## Candidate evidence

Screening, confirmation, capacity, active, cold, sensitivity and timed fault evidence are pending. The smoke run at the calibration revision had nine healthy windows and exercised native admission in both active and cold workloads. Smoke is an instrumentation check and does not support acceptance.
