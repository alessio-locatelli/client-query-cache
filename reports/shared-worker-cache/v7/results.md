# Version 7 results

Performance evidence is incomplete. Baseline calibration is complete; candidate measurements remain pending. The [registration](registration.md) defines the required phases, inference and acceptance bounds.

## Calibration

Fresh baseline-only calibration ran at clean revision `5acd958854e31e17c04d2df629fab06c5c6769f7` with pending configuration SHA-256 `06f7e1adc2ac0707a3469c3e03145ccd1eae7458131b178272518affe7347fee`. All 114 probe and 180 validation windows were healthy, with no read exceptions.

| Family      | Frozen reads/s |            Window duration |
| ----------- | -------------: | -------------------------: |
| Primary     |          1,020 |      30 s hot; 60 s active |
| Cold        |          1,000 | 10 s for 10,000 identities |
| Sensitivity |            372 |                       30 s |

The first primary-rate attempt at 2,040 reads/s failed qualification in all three one-worker synchronous direct-read windows. One missed the completion threshold; two failed the bounded-queue criterion. These windows remain in the calibration report. The registered halving rule selected 1,020 reads/s, which passed every primary validation window. Cold and sensitivity passed their first selected rates. Calibration is excluded from promotion inference.

The owner transport recovery fix changes neither baseline path. The frozen performance configuration has SHA-256 `0b74334c1c7962a8d8bb15af8cce3798fd0b8a4426c44b404b3eb6df261d14b7`. Candidate measurements remain pending and will record their source revisions separately. Raw calibration output remains untracked; reproduce it with the commands in the registration.
