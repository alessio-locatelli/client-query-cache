# Validated benchmark runtime reduction

**Use fresh baseline qualification instead of repeating saturation calibration.** The [version 9 preregistration](../v9/registration.md) preserves candidate durations, populations, blocks, inference, capacity and fault coverage. Its 38-window qualification took **34.72 minutes**, replacing at least **3.841 hours** of version 8 calibration: **at least 3.26 hours saved** per complete study. The performance study is forecast at **about 11 hours**, plus smoke, faults and analysis. This is a forecast, not a measured complete rerun or a comparison with the maintainer's approximate 24-hour session.

This completes [issue #278](https://github.com/alessio-locatelli/client-query-cache/issues/278)'s investigation and supplies the protocol for the [miss-cost continuation, issue #279](https://github.com/alessio-locatelli/client-query-cache/issues/279). It supersedes the stopping recommendation in the [initial analytical report](results.md), whose accounting and simulations remain useful. Version 7/8 evidence and issue #272's unsuccessful version 8 outcome remain frozen. These experiments do not promote a candidate.

## Measurements and cost

The [empirical plan](empirical-plan.md), then the [validation plan](validation-plan.md), were committed before their respective observations. Validation used clean revision `1b8fa7b58aafeaf3956f0752b1a2d439b3b71d47`, Python 3.14.7, PyMongo 4.18.2 and the registered two-CPU/2-GiB MongoDB container on an i3-13100 host. Each window recreated its catalogue, clients, workers, owner and cache. Qualification and validation had tracing disabled.

| Experiment                         | Windows | Command wall time | Result                                                            |
| ---------------------------------- | ------: | ----------------: | ----------------------------------------------------------------- |
| Instrumentation check              |       3 |        about 66 s | Healthy; each trace contained exactly 3,018 completed reads       |
| Hot discovery, six balanced blocks |      18 |          832.21 s | Healthy; direct-path short prefixes did not establish equivalence |
| Baseline qualification             |      38 |        2,083.39 s | All 38 passed existing validation checks                          |
| Fresh active comparison            |      78 |        4,803.88 s | Healthy; both shorter conditions failed equivalence               |

The approved qualification/validation batch took **114.79 minutes**, below its three-hour cap. Including discovery, instrumentation, the initial 66.75-second simulation and subsequent numerical analyses, cumulative experimental execution was approximately **2 hours 12 minutes**, including command setup and excluding editing, review and idle time. No complete historical study or saturated calibration was rerun.

Stage totals below are seconds across each batch's windows. Preparation covers catalogue construction. Startup/readiness spans preparation completion through worker collection and residency verification, including overlapping priming. Drain includes post-window sampling and invalidation drain. Teardown spans process stop through resource exit. Elapsed stages are disjoint; warmup and measurement are scheduled durations.

| Batch         | Preparation | Startup/readiness | Warmup | Measurement | Drain | Teardown | Other window time |
| ------------- | ----------: | ----------------: | -----: | ----------: | ----: | -------: | ----------------: |
| Discovery     |       15.25 |            219.93 |      0 |      540.00 |  1.30 |    20.42 |             18.10 |
| Qualification |       30.12 |            365.52 | 300.00 |    1,296.00 |  2.46 |    38.64 |             38.30 |
| Validation    |       71.19 |            767.87 | 780.00 |    2,989.80 |  6.17 |    96.64 |             78.47 |

Other window time is predominantly the one-second scheduled lead. Container startup was 1.38–1.53 seconds per batch; shutdown was 0.31–0.36 seconds. Serialization and command initialization explain the remaining difference from command totals. Preparation, drain and teardown do not dominate. Priming is necessary initialization; it cannot be removed while claiming fresh resident caches.

## Why qualification can be shorter

Version 8 calibration had 294 windows: saturated probes, repeated validation and an overloaded rate attempt followed by halving. The new procedure qualifies the frozen conservative rates once at each of the **38 baseline combinations**: twelve hot, ten active, eight cold and eight sensitivity windows. It preserves their workloads and checks errors, overflow, completion, backlog and sample floors with `validation_failure`. Cold qualification requires all misses. Every subsequent candidate window must pass the same health checks.

All 38 fresh qualifications passed. Retrospectively, each first validation repetition also detects the known overloaded primary rates in both versions 7 and 8. This does not estimate rare-overload probability. The safety argument requires unchanged baseline implementations, environment qualification and fresh health checks throughout candidate timing. A failed qualification makes the study inconclusive; the [preregistration](../v9/registration.md) defines invalidation and baseline-only recalibration.

All six generated candidate performance-phase schedules are identical between versions 8 and 9. No candidate measurements select offered rates. Qualification is a prerequisite, not a candidate block or a substitute for capacity measurements.

## Why active windows stay at sixty seconds

Fresh comparisons used 60 seconds/200 writes, 27.6 seconds/92 writes and 20.1 seconds/67 writes. Each retained one write every 0.3 seconds, aggregate read rate 1,006/s, query/data mix and ten-second warmup. Six mixed-model blocks balanced path orders and condition positions. Four additional pure-model cells supplied health/coverage diagnostics, not independent precision. Shortening explicitly reduced invalidated identities and lag captures; it did not preserve 200 writes.

The fixed equivalence rule required paired nominal 95% intervals, including both seeds and each block omission, within ±0.10 ms for P95, ±0.25 ms for P99, ±50 ms for lag P95 and ±5% for CPU/read, MongoDB bytes/read and steady group memory. Failures were:

| Short condition | Path/metric            | Interval for change | Allowed margin |
| --------------- | ---------------------- | ------------------: | -------------: |
| 27.6 s          | Direct sync P95        | −0.149 to +0.035 ms |      ±0.100 ms |
| 27.6 s          | Direct async P95       | −0.195 to +0.045 ms |      ±0.100 ms |
| 27.6 s          | Direct sync P99        | −0.285 to +0.145 ms |      ±0.250 ms |
| 27.6 s          | Direct async P99       | −0.337 to +0.092 ms |      ±0.250 ms |
| 27.6 s          | Independent bytes/read |    −6.25% to −5.49% |            ±5% |
| 27.6 s          | Shared bytes/read      |  −20.41% to −19.65% |            ±5% |
| 20.1 s          | Independent bytes/read |  −13.73% to −13.61% |            ±5% |
| 20.1 s          | Shared bytes/read      |  −36.56% to −36.36% |            ±5% |
| 20.1 s          | Shared CPU/read        |    −5.16% to +1.58% |            ±5% |

Both reference and 27.6-second single-block diagnostics passed all 32 point checks. Those passes cannot override failed equivalence. Independent windows made 172 native finds at sixty seconds, 65 at 27.6 seconds and 33 at 20.1 seconds, identically across the six mixed blocks. The read loop takes about 16.3 seconds to revisit the 16,384-identity catalogue. Shorter stops leave less time to reread invalidated identities, changing miss/admission work per read even at fixed write cadence. This does not attribute every shared-path extra miss to that mechanism.

Keeping 200 writes in a shorter window increases intensity and answers a different workload question. Six complete lag captures at the retained twenty-event size and sixteen-event gaps require 200 scheduled events and sixty seconds at this cadence. Historical twelve-block lag resampling at one through five captures showed poor near-limit power in at least one cell under an iid-block sensitivity model. Six behaved better in that model, but twelve historical blocks cannot validate correlation uncertainty or positively select a capture count. Fresh workload-equivalence failures suffice to reject the tested duration reductions.

## Precision and practical cost frontier

The [initial report](results.md#precision-versus-independent-observations) searches 3/6/12/24 blocks and 1,000–60,000 requests, including clustering, drift and rare stalls. Six blocks fail the predefined 80% power requirement even with independent requests; three also fail the 5% error requirement. Twelve blocks with 2,500 requests qualify under the independent model but fail under ten-request clustering. Twenty-four blocks with 5,000 requests qualify under both models, but repeat expensive setup, change cold-identity coverage and do not yield a cheaper equivalent complete study.

These models do not universally certify the inherited protocol. Strong between-block correlation can invalidate its inference too. Discovery's median worker correlations between adjacent completion latencies were +0.266 direct, −0.326 independent and −0.320 shared. These descriptive correlations are not effective-sample estimates. Real temporal comparisons and clustered simulations both prevent treating requests as independent experimental repetitions.

| Reduction                                        |           Relevant saving | Evidence/decision                                                                       |
| ------------------------------------------------ | ------------------------: | --------------------------------------------------------------------------------------- |
| Saturation calibration → qualification           |           At least 3.26 h | Validated; adopt                                                                        |
| Hot 30 → 10 s                                    |        1.40 h measurement | Direct-path discovery intervals exceed precision margins; retain                        |
| Active 60 → 27.6 s                               |        1.62 h measurement | Fresh equivalence fails; retain                                                         |
| Fewer blocks/lower floors                        | Potentially several hours | Known-effect criteria or cold coverage fail; retain                                     |
| Sensitivity 32 → 3/10/15 s                       |          0.29/0.22/0.17 h | Too few requests at 319/s; clustered precision gives no justification                   |
| Cached warmup 10 → 1 s everywhere                |            At most 1.05 h | Hot discovery suggests opportunity; active/sensitivity/resource equivalence unvalidated |
| Capacity 15 → 3 s                                |                    0.54 h | Saturated-throughput settling unvalidated; retain points/repetitions                    |
| Reuse live workers/caches; omit cold/fault cases |   Potentially substantial | Changes independence, initial state or coverage; excluded                               |

Retain hot 30 seconds, active 60 seconds, sensitivity 32 seconds, twelve confirmation/active/cold blocks, six screening blocks, three sensitivity blocks and the 10,000 percentile floor. Cold retains 10,000 new identities per window and no warmup. Capacity and all 75 fault trials remain required.

| Complete-study accounting           |      Hours |
| ----------------------------------- | ---------: |
| Version 8 acquisition lower bound   |     13.705 |
| Less its calibration lower bound    |     −3.841 |
| Plus measured qualification command |     +0.579 |
| New acquisition lower bound         | **10.443** |
| Forecast with measured overhead     |  **10.99** |

The forecast adds measured median residual overhead to each historical candidate window's scheduled measurement, warmup and maximum worker priming. Residuals are grouped by profile, model, worker count and path. Six missing shared groups borrow the same model/path's nearest observed worker count, preferring the same profile; output names each substitution. Estimated candidate hours are screening 1.504, confirmation 2.062, capacity 1.579, active 4.105, cold 0.544 and sensitivity 0.617. This is a planning estimate, not a confidence interval. It includes qualification's measured driver but excludes candidate command/container initialization, smoke, fault setup/teardown and analysis. Historical full-command timers for those stages are unavailable; faults must be budgeted separately, never as zero cost.

Under the retained schedules, the forecast is about 5% above the accounted acquisition lower bound. Even removing all candidate setup and warmup leaves 6.495 hours of candidate measurement: halving an eleven-hour performance study requires another workload or inference change. This is the **smallest validated protocol in the searched frontier**, not proof of a global optimum. Warmup or intermediate-duration changes may save more, but evidence does not justify deploying them. Fresh validation across all affected profiles would require further experiments; that is not required to use the validated calibration saving. Smoke/reduced configurations remain useful development diagnostics, excluded from acceptance.

## Reproduce

Use retained untracked version 7/8 reports as described in the initial report. The driver uses the contributor environment and disposable MongoDB. These commands reproduce the experiments; the qualification/validation pair requires advance multi-hour batch approval under issue #278.

```bash
source scripts/testcontainers-bridge.sh
PYTHONPATH=. uv run -- python research/shared_cache_runtime/experiment.py --mode discovery --output /tmp/agents/issue-278/discovery-reproduced.json
PYTHONPATH=. uv run -- python research/shared_cache_runtime/experiment.py --design reports/shared-worker-cache/runtime/qualification.json --output /tmp/agents/issue-278/qualification-reproduced.json
PYTHONPATH=. uv run -- python research/shared_cache_runtime/experiment.py --design reports/shared-worker-cache/runtime/validation.json --output /tmp/agents/issue-278/validation-reproduced.json
PYTHONPATH=. OPENBLAS_NUM_THREADS=1 uv run --with numpy==2.3.4 --with scipy==1.16.3 -- python research/shared_cache_runtime/analysis.py --qualification <qualification.json> --validation <validation.json> --discovery <discovery.json> --runtime-reference <historical-report-directory> --output /tmp/agents/issue-278/analysis-reproduced.json
PYTHONPATH=. OPENBLAS_NUM_THREADS=1 uv run --with numpy==2.3.4 --with scipy==1.16.3 -- python research/shared_cache_runtime/analysis.py --historical-active <v8-active.json> --output /tmp/agents/issue-278/lag-reproduced.json
```

The last command reproduces preregistered 1/2/3/6-capture sensitivity; `historical_lags(path, (4, 5))` adds intermediate exploratory counts without repeating it. Discovery analysis compares prefixes after one second with seconds 10–30 using six paired Student t intervals; overlapping slices are exploratory. Trace collection added about 0.132 microseconds/request in the local append probe and is excluded from fresh equivalence and acceptance. Raw reports retain stage boundaries, memory samples, environment, design, schedule and program hashes; they stay untracked.

| Raw input     | SHA-256                                                            |
| ------------- | ------------------------------------------------------------------ |
| Discovery     | `2ef74f4907dce0f823e06bda5b1200980cc88b77ed2043b03659125ad2d0cff3` |
| Qualification | `8b2005833b30b4a7bbdf8a992be77b0a7d4dc65851116557c858bd8e60046dc9` |
| Validation    | `e569e596c76efc12361255968bdfff33b0d83ffa26a44e8e33c0206ddafa25e7` |
