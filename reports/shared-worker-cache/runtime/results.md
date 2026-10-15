# Shared-cache benchmark runtime and precision

**Initial analytical stage; superseded by the [completed empirical investigation](empirical-results.md) and [version 9 preregistration](../v9/registration.md).** Recommendations and missing-evidence statements below describe the first stage, before fresh experiments.

**Recommendation: retain the current acceptance protocol for now.** The investigation for [issue #278](https://github.com/alessio-locatelli/client-query-cache/issues/278) rules out several large reductions, but does **not** establish a minimum practical runtime or validate the current protocol against every dependence model. That acceptance item remains open. No registration changes or candidate timings result from this study; [version 7](../v7/results.md), [version 8](../v8/results.md) and issue #272 keep their recorded conclusions.

The [plan](plan.md) fixed the precision requirements before alternatives were compared, at commit `c7f998c706abd6bbeeb72a8b1b2558dbb5814be6`. The analysis reuses all fourteen available version 7/8 calibration and performance reports. All 2,136 windows completed setup; overloaded calibration validations remain included. Request sequences and orchestration timers were not retained. The maintainer's approximately 24-hour estimate describes the previous session, whose boundaries are unknown; it is not an elapsed timer for either study.

## Where the time goes

Hours below are reconstructed **lower bounds**, excluding timed faults, smoke, diagnostics, analysis and unmeasured overhead. Measurement and warmup are scheduled durations. Priming sums the longest recorded worker duration in each window, since workers overlap; it omits owner priming and spawn delays. Each window also has a one-second scheduled start lead.

| Version 8 phase      |   Windows | Measurement |    Warmup | Worker priming | Start leads | Known lower bound |
| -------------------- | --------: | ----------: | --------: | -------------: | ----------: | ----------------: |
| Baseline calibration |       294 |       2.355 |     0.683 |          0.721 |       0.082 |             3.841 |
| Screening            |       108 |       0.900 |     0.300 |          0.199 |       0.030 |             1.429 |
| Confirmation         |       144 |       1.200 |     0.400 |          0.319 |       0.040 |             1.959 |
| Capacity             |       162 |       0.675 |     0.450 |          0.297 |       0.045 |             1.467 |
| Active               |       180 |       3.000 |     0.500 |          0.425 |       0.050 |             3.975 |
| Cold                 |       144 |       0.400 |         0 |          0.001 |       0.040 |             0.441 |
| Sensitivity          |        36 |       0.320 |     0.100 |          0.162 |       0.010 |             0.592 |
| **Total**            | **1,068** |   **8.850** | **2.433** |      **2.125** |   **0.297** |        **13.705** |

Version 7's corresponding total is 13.614 hours: 8.817 measurement, 2.433 warmup, 2.067 priming and 0.297 start leads. These are per-study costs; running both full studies costs at least 27.319 hours. The rough session estimate cannot resolve whether some work preceded that session.

| Component outside these totals | What the evidence establishes                                                                                                                                                                                                                                                                                                                           |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Data preparation               | Every window drops and repopulates its database, generates documents and encodes their sizes. No elapsed timer exists.                                                                                                                                                                                                                                  |
| Process startup                | Fresh workers and, for the shared path, an owner. Startup includes priming, so adding the 120-second deadline would double-count it and mistake a limit for consumption.                                                                                                                                                                                |
| Container startup              | One disposable replica set per phase command, not per window. Its elapsed time is unavailable.                                                                                                                                                                                                                                                          |
| Drain                          | Outstanding reads and owner invalidations must finish. The 10-second drain allowance is not measured elapsed drain.                                                                                                                                                                                                                                     |
| Teardown                       | Processes, connections and proxies close per window; the replica set closes per command. The 15-second shutdown deadline is not consumed time.                                                                                                                                                                                                          |
| Analysis                       | A narrow local probe takes a median 0.0101 seconds per 10,000 three-block bootstrap draws and 0.0241 seconds at twelve blocks. A profile attributes most work to random-index generation. Extrapolation suggests minutes, not hours; sorting larger draw populations and other estimands add uncertainty. Historical command durations are unavailable. |
| Faults                         | All 75 trials remain required. Event-relative recovery durations in the reports omit complete trial setup and teardown, so summing them would understate phase runtime.                                                                                                                                                                                 |

The source for this accounting is [the runner](../../../benchmarks/stream_cost/shared_cache/run.py), [window lifecycle](../../../benchmarks/stream_cost/shared_cache/window.py), [dataset preparation](../../../benchmarks/stream_cost/shared_cache/dataset.py) and [bootstrap](../../../benchmarks/stream_cost/shared_cache/analysis.py). Calibration and active traffic alone account for 7.816 hours of the version 8 lower bound.

## Precision versus independent observations

The simulation measures a single additive percentile criterion with known effects. It uses the registered mean of paired per-window percentiles and the upper end of a two-sided 95% bootstrap interval, with seed and omission checks. Its 2,000 bootstrap draws are exploratory, not a proposed replacement for acceptance draws. See the plan for distributions and error requirements. Dependence, asymmetric-stall and drift sensitivities are assumptions; they are not fitted to the retained summaries.

For P99 with independent requests:

| Blocks | Samples/window/path | Median bound width, ms | Acceptance at 0.8 ms | False acceptance at 1.0 ms |
| -----: | ------------------: | ---------------------: | -------------------: | -------------------------: |
|      3 |              10,000 |                  0.128 |                70.6% |                      12.9% |
|      6 |              10,000 |                  0.104 |                77.7% |                       3.5% |
|     12 |               1,000 |                  0.121 |                75.8% |                       1.8% |
|     12 |               2,500 |                  0.097 |                92.4% |                       2.1% |
|     12 |              10,000 |                  0.083 |                97.3% |                       2.4% |
|     12 |              30,000 |                  0.080 |                98.0% |                       2.4% |
|     24 |              10,000 |                  0.061 |               100.0% |                       2.0% |

These are simulation frequencies, not guarantees. For twelve blocks and 10,000 independent samples, one-sided 95% Wilson limits are 96.6%–97.8% for power and 1.9%–3.0% for boundary error. At a 0.95 ms effect, only 15.2% pass and 32.6% are unstable; deferral near the limit is expected. Six blocks fail the predefined 80% power requirement even before request clustering: their power upper limit is 79.2%. Three blocks also fail the error requirement and cannot balance all six path orders.

Ten identical consecutive requests per cluster reduce effective observations. Twelve blocks with 10,000 requests then have only 76.9% power (upper limit 78.5%), although median P99 width is 0.120 ms. With both P95 and P99 requirements enforced, the smallest tested sample populations qualifying under **both independent and clustered-request models** are 30,000 at twelve blocks and 5,000 at twenty-four blocks. Neither establishes a faster equivalent complete study: more blocks recreate startup and warmup, and changing cold identities changes its workload. Longer windows cannot replace fresh blocks: even six blocks with 60,000 requests fail the joint requirements.

The ten-request clusters are a within-window model. Separately, AR(1) dependence of 0.6 **between blocks** produces 13.9% boundary false acceptance at twelve blocks (upper limit 15.2%), and 12.3% at twenty-four. Resetting caches does not establish independence from host drift. Centered asymmetric stalls reduce twelve-block power to 76.9%; deterministic drift leaves 94.1% power but lowers near-limit acceptance. Thus the current sample floor and count cannot be certified against all planned models either. These results justify withholding a shorter protocol, not claiming the existing one is universally reliable.

Historical cold blocks reinforce that distinction. P95 paired standard deviations range from 0.048 to 0.096 ms; P99 ranges from 0.209 to 0.502 ms, exceeding the simulation's 0.15 ms block-noise assumption in several cells. Early/late P99 mean differences range from -0.399 to +0.103 ms. Twelve observations cannot distinguish drift from isolated stalls reliably; their lag-one correlations are descriptive only.

| Cold P99 cell | Twelve-block exploratory bound width, ms | Fraction of 64 balanced six-block subsets passing all stability checks |
| ------------- | ---------------------------------------: | ---------------------------------------------------------------------: |
| v7 sync / 4   |                                    0.111 |                                                                  56.3% |
| v7 async / 4  |                                    0.153 |                                                                  32.8% |
| v7 sync / 8   |                                    0.135 |                                                                   1.6% |
| v7 async / 8  |                                    0.134 |                                                                  12.5% |
| v8 sync / 4   |                                    0.114 |                                                                 100.0% |
| v8 async / 4  |                                    0.320 |                                                                  50.0% |
| v8 sync / 8   |                                    0.158 |                                                                  18.8% |
| v8 async / 8  |                                    0.187 |                                                                  10.9% |

Each subset contains one of the two blocks at each of the six path orders. These overlapping subsets are not independent trials; their fractions are not decision-error probabilities. The low-draw bootstrap also differs from registered inference. Published outcomes remain authoritative.

For independent requests, the approximate 95% rank half-width for P99 is 0.617 percentage points at 1,000 samples, 0.195 at 10,000 and 0.113 at 30,000; the P95 values are 1.351, 0.427 and 0.247. These follow `1.96 * sqrt(p * (1-p) / n)` and say nothing about milliseconds without a latency distribution. [NIST's percentile discussion](https://itl.nist.gov/div898/handbook/prc/section2/prc262.htm) explains the order-statistic basis. Request count cannot establish independent repetitions or tail coverage by itself.

## Which reductions survive workload constraints

| Alternative                                               | Version 8 cost implication                                                          | Constraint or evidence                                                                                                                                                                              |
| --------------------------------------------------------- | ----------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Hot: 30 → 10 seconds, twelve blocks                       | Known lower bound 12.305 h; saves 1.400 h, 10.2%                                    | 10,060 reads retain the floor. Retrospective summaries cannot establish shorter-window tails, memory peaks, CPU/wire precision or settling.                                                         |
| Hot: 3 or 15 seconds                                      | Three seconds offers 3,018 reads and fails the current floor; fifteen saves 1.050 h | Lower floors are parameters, but the clustered simulations reject large reductions; neither duration has fresh temporal validation.                                                                 |
| Sensitivity: 32 → 3/10/15 seconds                         | Saves 0.290/0.220/0.170 h of measurement                                            | Offers 957/3,190/4,785 reads at 319/s. The 10,000 floor needs 31.35 s, rounded to 32. Large documents and sorted finds cannot be omitted.                                                           |
| Six blocks plus ten-second hot windows                    | Known lower bound 9.517 h                                                           | Balanced order survives; predefined power and historical stability do not.                                                                                                                          |
| Twenty-four blocks plus ten-second hot windows            | Known lower bound 17.880 h                                                          | More repetitions improve some precision models, but repeat expensive setup.                                                                                                                         |
| Remove every recorded warmup and worker priming interval  | At most 4.558 h saved from these recorded components                                | Untested; clients, metadata, residency and worker initialization must still qualify. This is an optimistic bound, not a feasible optimization.                                                      |
| Reuse all baseline calibration                            | Removes 3.841 h of accounted components; total saving unknown                       | Only unchanged baseline code/workloads and a stable host could qualify. Existing `--reuse-probes` handles preregistered unaffected probes; it does not establish that old validation remains valid. |
| Reuse prepared documents or avoid re-encoding their sizes | Unquantified                                                                        | Immutable construction is distinct from database reset. No preparation timer exists; active writes and cold results require pristine state.                                                         |
| Reuse live clients, caches or workers                     | Unquantified                                                                        | Changes the independent-block lifecycle. Requires a new experimental design, not an equivalent-work speedup.                                                                                        |
| Reduce bootstrap draws                                    | Likely saves minutes                                                                | Adds no observations. Near-limit results require seed/omission stability; optimizing or reusing identical resampling schedules is preferable to weakening inference.                                |

Cost alternatives hold recorded per-window overhead and frozen rates constant, retain full calibration, and scale confirmation/active/cold setup when block counts change. They are analytical lower bounds, not executed protocols. Joint interactions can change overhead. Even perfect elimination of calibration, warmup and priming cannot make a tenfold reduction while retaining twelve active blocks: active **measurement alone** is three hours, exceeding one tenth of 13.705 hours. Smaller active and block designs have explicit statistical or coverage tradeoffs.

Active traffic requires a separate choice:

| Duration | Keep 200 writes                                  | Keep current cadence of 3.33 writes/s        |
| -------: | ------------------------------------------------ | -------------------------------------------- |
|     60 s | Current workload                                 | 200 writes; six complete lag captures        |
|     30 s | 6.67 writes/s; invalidation pressure doubles     | 100 writes; only three complete lag captures |
|     15 s | 13.33 writes/s; invalidation pressure quadruples | 50 writes; only one complete lag capture     |

Six captures of twenty events separated by sixteen events consume `6*20 + 5*16 = 200` invalidations. At fixed cadence they need the full current schedule. Doubling cadence may change lag, misses, CPU and throughput; its effect is **not measured** by existing reports or the latency simulations. No shortened active duration is recommended. Mixed traffic additionally needs at least 19.88 seconds for 10,000 reads in each model at 1,006 aggregate reads/s; fifteen seconds fails that current requirement regardless of write policy.

Cold retains 10,000 distinct, initially absent identities at 1,000 reads/s and twelve fresh blocks. Reducing its identities would test less cold admission work; increasing rate would change the frozen load. Capacity retains all 162 windows across workers and concurrency levels: a fixed-rate percentile simulation cannot validate maximum-throughput headroom. Faults retain every case, five repetitions and safety checks; their small event-relative durations do not justify deleting scenarios or shrinking expiry/readiness observation periods.

Shorter exposure also misses rare stalls. At an illustrative Poisson rate of one stall per 300 seconds, twelve 30-second windows miss every stall with probability 30.1%; twelve ten-second windows miss them with probability 67.0%. At one per 60 seconds those probabilities are 0.25% and 13.5%. Neither rate is measured; there is no universal minimum duration without defining a consequential stall and its occurrence rate. Fresh blocks cover setup variation; longer windows cover temporal exposure. They are complementary.

## Reproduce and execution cost

The [program](../../../scripts/analyze_shared_cache_runtime.py) pins its isolated numerical environment. Use the existing version 7/8 raw reports, named `v7-<phase>.json` and `v8-<phase>.json` for the seven performance/calibration phases above. They are untracked; request them from the maintainer rather than regenerate complete studies for this analysis.

```console
OPENBLAS_NUM_THREADS=1 uv run --script scripts/analyze_shared_cache_runtime.py --reports <raw-report-directory> --output /tmp/agents/issue-278/reproduced.json
```

The output retains input hashes and revisions. Without historical files, reproduce the known-effect simulations alone with `--simulate-only` instead of `--reports <raw-report-directory>`. Use a new output filename. No MongoDB instance or candidate benchmark is started. The recorded first batch predates the program-hash metadata and cost-grid helper added to the final script; it has input hashes but no execution-time program hash. Its numerical kernel was reviewed against the final source, and its saved simulation observations were reused for subsequent cost accounting.

The experimental batch was estimated at under five minutes, with a twenty-minute cap. It completed in **66.75 seconds wall time**, with 224 MiB peak RSS. Environment download/setup took under fifteen seconds; numerical reference checks and the narrow bootstrap probe took under three seconds combined. The reference checks covered constant effects, cached resampling weights, exact beta-order-statistic moments, Wilson endpoints, balanced subsets and agreement with the registered bootstrap on a small case. Validation costs are recorded separately in the untracked execution ledger. This investigation uses minutes of experimental execution, not its 24-hour allowance. Raw outputs remain under `/tmp/agents/issue-278/`.

## Remaining evidence and decision

Retain twelve confirmation/active/cold blocks, the 10,000 per-window sample floor, 30-second hot windows, 60-second active windows and the calibrated sensitivity duration. These values preserve the existing scope; the evidence does not prove they are optimal or universally sufficient. Use smoke or `--only MODEL:WORKERS` with disposable reduced-block configurations for development diagnostics, clearly excluded from acceptance.

A ten-second hot-window proposal is the cheapest plausible duration-only next step, but its potential saving is bounded at 1.4 recorded hours, so a full candidate-protocol rerun would be disproportionate. Before changing the protocol, issue #278 needs timestamped stage timings and representative time-ordered request/memory/lag observations, including warmup transitions and rare stalls, to validate temporal shortening and any setup/calibration reuse. Those data are absent here; the maintainer was asked for historical timers. Aggregate quantiles cannot recover them. A targeted, preregistered validation should test the most promising alternative and near-limit reliability, with its cost approved in advance if multi-hour. Until that evidence exists, near-minimum runtime remains unresolved and no new acceptance preregistration is justified.
