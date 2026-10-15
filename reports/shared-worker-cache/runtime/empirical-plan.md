# Empirical continuation

This continuation of [issue #278](https://github.com/alessio-locatelli/client-query-cache/issues/278) resolves the missing observations identified in [results.md](results.md). The prior report is exploratory; its stopping point does not establish a minimum runtime.

## Discovery

Collect six balanced fresh paired blocks of the primary hot workload at eight asyncio workers, with 30 measured seconds and no discarded warmup. Retain completion timestamps, latencies, memory samples and elapsed preparation/startup/ready/drain/teardown boundaries. Inspect prefixes and settled intervals of 3, 5, 10, 15 and 30 seconds. Complete residency and initialized metadata still precede traffic. Read rate, catalogue, three paths and decode work remain version 8's.

A separate three-window instrumentation check uses the full primary catalogue, one discarded warmup second and three measured seconds. It checks trace lengths against completed reads and verifies timing boundaries; it cannot support acceptance. Expected cost is under three minutes. Discovery is estimated at 15–20 minutes with a 30-minute hard limit. Including setup/analysis, this initial batch is capped at 45 minutes; cumulative experimental execution is recorded alongside the prior ledger.

Trace timestamps observe completion immediately after the existing latency endpoint; they add one clock read and a lock-protected append. Measure that overhead separately and use traces only for coarse time intervals. Fresh validation uses the unmodified latency path so tracing cannot certify its own absence of perturbation.

Use the prior [precision criteria](plan.md#decision-requirements), preserving whole paired-block experimental units. Estimate dependence from actual ordered observations, rather than certifying or rejecting a duration from an arbitrary correlation model alone. Evaluate known-effect simulations around the limits using measured variability; distinguish acquisition noise from Monte Carlo error. Keep near-limit deferral as a valid decision. Calibrate simulated type-I error and power before selecting block-count or inference changes.

## Validation and coverage

Choose the next experiment from discovery, commit its exact durations, repetitions, warmup, precision/decision rules and cost estimate before fresh measurements, and use disjoint blocks. Evaluate any active duration change with both fixed cadence and fixed count explicitly; no result may claim both were preserved. Retain cold identities, capacity points and all fault scenarios unless evidence supports a declared change. No existing complete phase suite or baseline calibration is rerun to establish a reference.

The target is a complete-study runtime recommendation, including setup/calibration savings and evidence excluding substantially cheaper alternatives. Conditional reuse of baseline calibration must specify code/workload/host invalidation and fresh qualification. A new acceptance registration must precede subsequent candidate timing. Individual batches stay below two hours unless the maintainer explicitly approves a larger batch; the original cumulative 24-hour execution ceiling remains authoritative.
