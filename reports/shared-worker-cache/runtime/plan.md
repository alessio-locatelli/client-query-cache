# Exploratory runtime study plan

This plan addresses [issue #278](https://github.com/alessio-locatelli/client-query-cache/issues/278). It is fixed before running alternative comparisons. It authorizes no candidate acceptance measurements or changes to the version 7/8 registrations.

## Decision requirements

A shorter acceptance protocol must preserve all required cells, balanced path order, fresh paired blocks, offered read rate, query/data mix, cold identities, capacity coverage and timed fault scenarios. A fixed budget ends in deferral when precision is inadequate. There is no sequential stopping or repeated search for a passing seed.

For the simulated single additive-latency criterion, require a one-sided 95% Wilson upper bound on false acceptance of at most 5% at and above the 1 ms limit, and a corresponding lower bound on acceptance of at least 80% for a true 0.8 ms effect. These are per-criterion requirements; the all-must-pass gate cannot increase false acceptance of an unsafe criterion. Require median upper-bound minus point-estimate widths no larger than 0.10 ms for P95 and 0.25 ms for P99. A 0.95 ms effect deliberately tests near-limit deferral; it has no required power. A model failure rejects a reduction, while model success alone cannot authorize one.

## Search and inference

- Sample populations per path/window: 1,000, 2,500, 5,000, 10,000, 30,000 and 60,000; fresh blocks: 3, 6, 12 and 24. Three blocks deliberately diagnose loss of six-order balance and are ineligible for acceptance.
- Historical version 7/8 cold P95/P99: retain paired path statistics, report standard deviations, early/late drift and lag-one correlation; compare all 64 balanced six-block subsets (one from each path order) with the twelve-block estimate. Subsets are exploratory, never new independent observations.
- Simulations: 2,000 independent studies per setting, seed 278, P95/P99; baseline latency is lognormal with median 1 ms and log-scale standard deviation 0.4. Use exact uniform order statistics transformed through that distribution, then center the finite-sample path difference on known effects 0.8, 0.95, 1.0 and 1.05 ms. This estimates the mean of per-window percentiles, matching the registered delta estimand.
- Request dependence: compare independent samples with clusters of ten identical consecutive requests, reducing the number of independent order statistics by ten. This is an explicit stress model, not an estimate of real autocorrelation.
- Between-block noise: Gaussian paired variation with standard deviation 0.15 ms. Separately add centered exponential variation of scale 0.15 ms for asymmetric stalls; separately introduce AR(1) dependence of 0.6 across successive blocks. A deterministic drift case adds a linear -0.15 to +0.15 ms trend. These are sensitivity assumptions, not fitted distributions.
- Use whole paired-block percentile bootstrap upper bounds at the 97.5th percentile (the upper end of the registered two-sided nominal 95% interval), with 2,000 draws, a second seed and each block omitted. Cache resampling counts per block count/seed. Classify pass only if every upper bound passes, fail if every bound fails, and otherwise unstable. Report Monte Carlo uncertainty; 2,000 draws are exploratory and do not replace registered acceptance draws.
- Compute rank-space uncertainty for percentile samples and the chance of missing a Poisson stall over the measured exposure, at illustrative rates of one per 60 and 300 seconds. These rates are not empirically established.

## Runtime accounting and scope

Reconstruct calibration, measurement, warmup, one-second start leads and critical-path priming from reports and runner source. Label data preparation, process/container startup, drain, teardown and analysis as unmeasured unless independently timed. Deadlines are bounds, never consumed durations. Hash input files and retain revision/configuration identifiers in untracked output.

Compare hot/sensitivity windows of 3, 10, 15 and 30 seconds and active windows of 15, 30 and 60 seconds, independently of block counts. Use the actual frozen rates to evaluate sample floors, including each half of mixed traffic. Evaluate both fixed write cadence and fixed 200-write count for active reductions; six lag captures need their registered event coverage. Cold identity counts, capacity points and fault cases are separate constraints, never silently removed.

The initial analytical/simulation batch is capped at 20 minutes including environment setup; expected execution is under five minutes and validation under five more. Record actual commands and durations. No full calibration or benchmark phase reruns. The cumulative experimental limit is 24 hours, and any multi-hour batch needs maintainer approval in advance. If stage timers or request series are essential to a stronger conclusion, request them rather than regenerate the full study.
