# Design

## Context

See [proposal.md](proposal.md) for motivation. `synchronous/streams.py` and `asynchronous/streams.py` each define a 1,000 ms constant and pass it to `Database.watch()`. Their coordinators construct supervisors without a public setting. `CacheManager` owns one coordinator and accepts only cache sizing configuration. The existing benchmark infrastructure can isolate a replica set, measure its container CPU and direct-path bytes, and retain versioned decision evidence. Its `stream_polls` counter increments around `ChangeStream.next()`, which can issue multiple `getMore` commands internally, so that counter cannot measure wire-level idle polling.

MongoDB defines `maxAwaitTimeMS` as an upper bound for an empty `getMore` batch. A waiting change stream keeps a connection occupied. PyMongo can impose an operation or socket timeout independently of this setting. The existing invalidation-lag telemetry is calibrated only for the replica-set benchmark topology.

## Goals / Non-Goals

**Goals:**

- Choose one default using reproducible measurements and a decision rule fixed before sampling.
- Preserve one setting per manager across all its database streams and reconnects, with identical sync and async behavior.
- Keep production measurement labels truthful without adding command-monitoring overhead to every application.

**Non-Goals:**

- Guarantee a maximum time to detect every network partition or deliver every change event.
- Claim a replica-set measurement proves identical results for sharded clusters or every deployment.
- Add process-wide configuration or change the caller-owned PyMongo client's timeout settings.

## Decisions

### Compare candidate values before changing the default

Register 1,000, 5,000, 10,000, 30,000, and 60,000 ms as candidates before the first sample. Use a dedicated benchmark client and one database-scoped stream for each run. Compare an idle window, a paced relevant-write window, and a burstier relevant-write window with the same data, schedules, and operation counts at every value. Run six counterbalanced blocks on the same isolated replica-set topology; reset the cache and stream between runs and warm up before sampling. Run both sync and async paths. Start each idle sampling window at an observed `getMore` boundary and keep it open for at least 120 seconds and until two complete `getMore` waits finish; report actual counts rather than assuming the requested wait is the observed cadence. Each active window processes at least 200 relevant writes, with their exact issue offsets fixed in the pre-run configuration.

Attach a command listener to the dedicated benchmark client to count actual `getMore` commands and capture their `maxTimeMS`; retain only counts and timing metadata, never command bodies or credentials. Reuse the existing container CPU and direct-path proxy measurement facilities. Normalize idle CPU, byte, and command counts by each window's measured elapsed time before comparing rates, since waiting for complete final commands can make idle windows slightly different in length. Measure manager shutdown separately when an idle `getMore` is in flight, as well as write-to-invalidation lag during active windows. Record versions, topology, timeout options, resource limits, elapsed times, repetition order, all candidate outcomes, and failed or inconclusive runs. The report validator checks matched schedules, successful event processing, and measurement completeness. A process or server timeout that invalidates a run is reported as a failed candidate, not converted into a resource saving.

This extends the existing stream-cost benchmark rather than relying on the old `stream_polls` counter or comparing historical reports from different hosts. The alternative of inferring request rate as `1 / maxAwaitTimeMS` would miss driver and server behavior and would not measure CPU, bytes, or shutdown.

### Freeze a conservative selection rule before running the matrix

Before collecting any samples, freeze a versioned pre-run configuration containing the full candidate list, six-block order, window durations, write offsets and tolerances, shutdown-trial schedule, 95% family-wise confidence level, block-bootstrap method and resample count, and the gates below. The report records the configuration's content hash. Resample whole paired blocks, preserving each block's events and within-block dependence. For latency, compute p95 from pooled events in the sampled blocks, then form a one-sided upper confidence bound for each candidate-to-baseline p95 ratio from the paired block resamples. Apply the same paired-block approach to CPU and byte ratios; compute shutdown p95 from repeated trials across blocks. Pre-register the complete family of candidate-to-baseline gate comparisons and pairwise candidate-ranking comparisons, and apply Holm-Bonferroni adjustment to their one-sided bootstrap p-values or equivalent simultaneous upper bounds; every claimed saving, noninferiority result, or pairwise win must survive that adjustment. If the baseline denominator is too close to zero for a stable ratio under the configuration's recorded resolution rule, that ratio cannot establish a saving or noninferiority. The gates are:

1. Candidate runs must complete without timeout or stream-health failures and process the same scheduled events as the 1,000 ms baseline.
2. For each active workload and execution model, the upper 95% confidence bound of the candidate-to-baseline p95 write-to-invalidation lag ratio must be at most 1.10. The upper bounds for active server CPU and benchmark-process CPU ratios must each be at most 1.05.
3. The candidate's p95 idle shutdown duration must be at most 2 seconds, with its uncertainty interval below that limit.
4. For each execution model, the adjusted upper confidence bound for idle benchmark-process CPU ratio must be at most 1.05. An eligible candidate must also have an adjusted upper bound of at most 0.95 for idle server CPU ratio or at most 0.90 for idle direct-path-byte ratio in each execution model. A candidate with no measurable CPU saving can therefore qualify through bytes, provided its client CPU and other gates pass.

Among eligible candidates, first compare each value's worse idle-server-CPU ratio across sync and async paths. Choose a lower-cost value only when the adjusted paired candidate-to-candidate comparison establishes lower CPU cost in both paths; otherwise compare worse direct-path-byte ratios and require an adjusted decisive byte reduction in both paths. If neither comparison establishes one winner, choose the shorter wait. Requiring a benefit in each path and ranking by the worse path gives one conservative default for both execution models; it never trades a clear regression in one path for a saving in the other. Retain individual blocks, all adjusted bounds, and their calculations in local generated reports for validation. Commit only a prose Markdown summary of every candidate outcome, failures, limitations, provenance, and reproduction commands. Keep raw observations and bootstrap distributions out of Git. A readable configuration under 200 lines deterministically expands the fixed schedules and comparison family without changing the measured protocol. If no larger candidate qualifies decisively, retain 1,000 ms and say that the comparison did not justify a change. Do not lower a gate or add a candidate after inspecting results. The fixed 2-second shutdown limit is a proposed library responsiveness budget; it is not a claim about present behavior. A pure request-count minimum would favor the largest value without considering those costs.

### Expose one explicit manager option

Add `max_await_time_ms` as a keyword-only `CacheManager` argument for sync and async managers. Omission uses one shared selected default; a supplied value is applied to every database stream on that manager, including reopened streams. Reject booleans, non-integers, non-positive values, and values beyond the conservative signed 32-bit millisecond range before opening a stream. Keep the common default and validation in one shared module to avoid drift between execution models. Do not add an environment-variable fallback: it would give two managers in one process an implicit shared setting and make the effective value less visible at construction.

Document the option in `docs/api-reference.md`, explain the measured default and limitations in `docs/stream-cost-benchmarks.md`, and keep the README brief. Explain that callers using nonzero PyMongo `timeoutMS` need a value greater than `max_await_time_ms`; socket timeouts and infrastructure idle timeouts also need consideration. The library does not rewrite those caller-owned settings.

### Correct measurement scope without changing the metric's value

Keep the existing `stream_polls` metric name and count, but describe it as worker calls to change-stream iteration. Amend documentation and benchmark labels where they imply a `getMore` count. The dedicated benchmark's command listener supplies the actual wire-command count. Changing the production metric to instrument PyMongo commands on every client would add monitoring overhead and complexity merely to support this decision.

## Risks / Trade-offs

- **Small idle CPU deltas are noisy** -> Keep repeated matched blocks and publish inconclusive results; retain 1,000 ms when the rule cannot distinguish values.
- **An await time interacts with timeouts or shutdown differently across deployments** -> Measure those outcomes, document the observed topology and client settings, and provide the per-manager override.
- **A larger wait may expose an existing stream-health gap** -> Test interruption and recovery with representative candidates; treat failures as blocking findings under the existing coherency contract instead of choosing a value that hides them.
- **A public option enlarges the API** -> Keep it on the manager alone with one validation path and no separate environment-variable behavior.

## Migration Plan

Existing callers omit the new argument and receive the measured default. Callers needing the prior 1,000 ms behavior can pass `max_await_time_ms=1_000`. The committed benchmark summary and documentation will state the actual chosen default and its rationale after measurement; this design intentionally does not predict that result.
