# stream-cost-benchmarking Specification

## Purpose

This capability provides controlled, reproducible workload reports for the cost and benefit of change-stream-backed local caching.

## Requirements

### Requirement: Raw and cache variants use equivalent workloads

The benchmark SHALL compare raw and cache variants with matched data, queries, timing, concurrency, and sample schedules.

#### Scenario: A paired workload is reported

- **WHEN** a benchmark writes a raw-versus-cache comparison report
- **THEN** the validator rejects it if either variant lacks a required matching workload parameter

### Requirement: Benchmark reports identify reproducibility context

Every benchmark report SHALL identify its revision, software versions, topology, resource limits, workload parameters, samples, and limitations.

#### Scenario: A report omits its execution context

- **WHEN** a report lacks a required revision, environment, workload, sample, or limitation field
- **THEN** report validation rejects it as insufficient to reproduce or interpret the comparison

### Requirement: Consolidated-stream workloads record topology and traffic

The benchmark SHALL record the stream topology and relevant and unrelated write traffic for consolidated-stream workloads.

#### Scenario: A consolidated stream is characterized

- **WHEN** a benchmark report claims to measure the cost of one database-scoped stream across cached collections
- **THEN** setup or report validation rejects it unless exactly one stream serves at least two cached collections in one database, the unrelated writes target collections in that same database, and the report records its collection-to-stream mapping plus both relevant and unrelated write traffic

### Requirement: Unrelated-write conclusions use a matched control

A claim about unrelated-write effects SHALL compare a control and loaded run with otherwise matched workloads.

#### Scenario: A router-lag conclusion lacks a control

- **WHEN** a report attributes an invalidation-lag increase to unrelated write traffic using only a single loaded consolidated-stream run
- **THEN** report validation rejects the conclusion for lacking the matched unrelated-writes-disabled control run

#### Scenario: A report over-claims router-only attribution

- **WHEN** a report attributes an end-to-end invalidation-lag increase specifically to router-internal serialization rather than to the delivery pipeline as a whole
- **THEN** report validation rejects the claim, since this workload does not instrument router-internal stage timing separately from server and transport time

#### Scenario: A saturated baseline is mistaken for a healthy pipeline

- **WHEN** a report concludes the delivery pipeline is not a bottleneck using only a flat control-to-loaded lag delta, without checking both runs' absolute lag against the pre-registered threshold
- **THEN** report validation rejects the conclusion, since a pipeline already saturated by relevant traffic alone would show the same flat delta

### Requirement: Matched runs begin from equivalent fresh state

Each run in a matched pair SHALL start with reset data, cache, and stream state and follow counterbalanced, warmed-up execution.

#### Scenario: A run reuses a prior run's mutated state

- **WHEN** a matched pair's control and loaded runs execute sequentially against the same database, cache, and stream without resetting between them
- **THEN** setup or report validation rejects the pair, since a lag difference could then be caused by carried-over document or cache state rather than unrelated write traffic

#### Scenario: A pair runs on a fixed order without warm-up

- **WHEN** a report runs a pair's two runs on the same replica-set topology without counterbalancing run order across repeated pairs or applying a pre-registered warm-up phase before each run
- **THEN** report validation rejects the attribution of any observed lag difference to unrelated-write traffic, since server-side cache warmth could differ between the runs independent of that traffic

#### Scenario: A pair uses a fresh topology per run

- **WHEN** a report provisions a separate replica-set topology for each run in a matched pair
- **THEN** report validation rejects the pair, since the two runs would then have different primaries and the pair's single shared clock-offset calibration was never estimated against the second run's server

### Requirement: Healthy conclusions require repeated passing pairs

A healthy consolidated-stream conclusion SHALL require repeated valid pairs and SHALL account for every failing pair.

#### Scenario: A healthy conclusion is certified from a single pair

- **WHEN** a report certifies the pipeline as healthy using only one pair's result, without the pre-registered minimum number of repeated, counterbalanced pairs
- **THEN** report validation rejects the certification, since a single pair cannot distinguish within-pair sampling variance from variation between repeated executions

#### Scenario: One failing pair is overridden by passing pairs

- **WHEN** a report certifies the pipeline as healthy because a majority (but not all) of the pre-registered repeated pairs satisfy both the corrected absolute-lag threshold and the control-to-loaded delta threshold with their required uncertainty and confidence bounds
- **THEN** report validation rejects the certification; any pair failing either threshold makes the overall result a failure, not an average or a majority vote

#### Scenario: A permissive delta rule masks a loaded-run failure

- **WHEN** a report concludes the delivery pipeline is healthy because the loaded run is not "meaningfully worse" than the control, while the loaded run's own absolute lag exceeds the pre-registered threshold
- **THEN** report validation rejects the conclusion, since the delta rule alone does not guarantee the loaded run itself is within the acceptable-lag threshold

### Requirement: Lag comparisons require sufficient relevant events

Each run in a pair SHALL process enough relevant invalidations to support its pre-registered lag percentile.

#### Scenario: A run has no relevant invalidations to sample

- **WHEN** a control or loaded consolidated-stream run completes with zero relevant writes processed or a lag-sample count below the pre-registered percentile's minimum
- **THEN** setup or report validation fails that run rather than allowing an empty or under-sampled distribution into a healthy-pipeline conclusion

### Requirement: Loaded runs overlap the required unrelated traffic

The loaded run SHALL meet a pre-registered unrelated-write minimum while relevant lag samples are collected.

#### Scenario: The loaded run falls short of the minimum unrelated-write load

- **WHEN** a loaded consolidated-stream run completes with its unrelated writer enabled but its observed unrelated-write count or rate falls below the pre-registered minimum
- **THEN** setup or report validation fails that run, since a below-minimum load does not meaningfully exercise the traffic pattern this workload is meant to characterize

#### Scenario: Unrelated writes do not overlap the sampling window

- **WHEN** a loaded run's unrelated writes meet the pre-registered minimum count or rate in total, but occur entirely outside the window during which relevant-write invalidation-lag samples are collected (e.g. only during warmup)
- **THEN** setup or report validation fails the run, since the sampled invalidations were never actually subjected to concurrent unrelated load

### Requirement: Relevant writes replay the same schedule

Control and loaded runs SHALL replay the same pre-registered relevant-write schedule within its timing tolerance.

#### Scenario: Relevant-write load differs between the control and loaded runs

- **WHEN** the control and loaded runs' observed relevant-write counts or rates fall outside the pre-registered tolerance of each other
- **THEN** setup or report validation fails the pair, since a difference in relevant traffic alone can change invalidation lag independently of unrelated writes and contaminate the comparison

#### Scenario: Matching counts substitute for a replayed schedule

- **WHEN** the control and loaded runs independently generate relevant writes at the same target count or rate, rather than each replaying the pair's one fixed, pre-registered write-issue schedule
- **THEN** setup or report validation fails the pair, since burst timing can differ between the runs even when aggregate counts match, and invalidation lag is sensitive to that timing

### Requirement: Clock offset is calibrated from primary round trips

The benchmark SHALL estimate server-to-host clock offset from current-primary round trips and include quantization uncertainty.

#### Scenario: Clock offset is estimated by minimum round-trip time

- **WHEN** the benchmark estimates the server-host clock offset
- **THEN** it samples the current primary's `hello` command `localTime` over multiple round trips, selects the minimum-round-trip-time sample, computes `offset = T_s − (t0 + t1) / 2` from server time `T_s` and host send/receive times `t0` and `t1`, and records half that sample's round-trip time plus one millisecond of BSON Date quantization allowance as the uncertainty bound

#### Scenario: Corrected lag uses the shared clock offset

- **WHEN** an event has server `wallTime` `W` and the manager applies its invalidation at host wall time `A`
- **THEN** the report computes corrected lag as `(A − W) + offset`, using the offset shared by both runs in the matched pair

#### Scenario: The quantization allowance is omitted from a low round-trip calibration

- **WHEN** a report computes calibration-noise uncertainty as half the selected round-trip time alone, without the one-millisecond BSON Date quantization allowance — most consequential for a low round trip, where quantization rather than jitter dominates the true error, but required regardless of round-trip magnitude
- **THEN** report validation rejects the uncertainty computation as omitting a required error source, though a low round trip itself is not rejected

#### Scenario: A later calibration sample omits the quantization allowance

- **WHEN** a report computes a non-initial calibration sample's own uncertainty as half its round-trip time alone, without the one-millisecond quantization allowance applied to the initial sample
- **THEN** report validation rejects the drift estimate's uncertainty as inconsistent, since every calibration sample is subject to the same BSON Date quantization regardless of its position in the sequence

#### Scenario: A monotonic clock is used for a cross-clock measurement

- **WHEN** the benchmark records `t0`, `t1`, or the invalidation-apply timestamp `A` using a monotonic clock rather than a wall clock
- **THEN** report validation rejects the corrected-lag computation, since a monotonic reading cannot be meaningfully compared against the server's wall-clock `wallTime`

### Requirement: Lag pairs use a stable host and primary

A paired lag comparison SHALL reject host clock steps and primary changes across its measurement window.

#### Scenario: The benchmark host's own wall clock is stepped during the pair

- **WHEN** the elapsed wall-clock duration between two paired readings diverges from the elapsed monotonic duration by more than the pre-registered tolerance
- **THEN** report validation rejects the pair, since the host's wall clock was adjusted during the interval independent of anything the primary-drift monitoring could detect

#### Scenario: The primary changes during a run

- **WHEN** a step-down or election changes the replica set's primary while a run is in progress
- **THEN** report validation rejects the entire pair's lag measurements, since the calibrated offset no longer corresponds to the server now originating the stream's events

#### Scenario: An election is detected only by electionId, not a topology event

- **WHEN** two consecutive calibration samples report different `electionId` values from `hello`, but the driver never surfaces a corresponding topology-changed event during the pair
- **THEN** the benchmark still fails the pair, since `electionId` comparison does not depend on the driver's heartbeat timing to detect the change

#### Scenario: electionId polling is skipped

- **WHEN** a report's calibration samples record `localTime` without also recording and comparing `electionId`
- **THEN** report validation rejects the pair for relying solely on the driver's topology events, which can lag the server's actual election

#### Scenario: The primary changes between the control and loaded runs

- **WHEN** a step-down or election changes the replica set's primary after the control run completes but before the loaded run starts
- **THEN** report validation rejects the entire pair, since the loaded run's events would originate from a different server than the one the shared offset was calibrated against

### Requirement: Lag thresholds and cadence are fixed before sampling

The benchmark SHALL pre-register an absolute lag threshold, comparison rule, and sampling cadence.

#### Scenario: A threshold is fixed before sampling

- **WHEN** a report includes an acceptable-lag threshold or a "meaningfully worse" comparison rule
- **THEN** report validation rejects it unless that threshold and rule were part of the pre-run configuration, not chosen after observing results

#### Scenario: A percentage-based comparison rule is used

- **WHEN** a report's "meaningfully worse" comparison rule expresses the control-to-loaded change as a percentage or ratio rather than an absolute difference
- **THEN** report validation rejects the rule, since the shared clock-offset uncertainty does not cancel out of a ratio the way it cancels out of an absolute difference

#### Scenario: A healthy conclusion is presented as a proven bound

- **WHEN** a report presents task 5.1's "not meaningfully worse" (healthy) conclusion without disclosing that it depends on the unverifiable assumption that no clock step-and-revert occurred between consecutive calibration samples
- **THEN** report validation rejects the conclusion for claiming a guarantee this benchmark's instrumentation cannot provide, since an undetected step's magnitude — unlike its possible duration — is not bounded by the sampling cadence

### Requirement: Lag deltas account for residual clock drift

The benchmark SHALL include total calibration and drift uncertainty in its control-to-loaded lag delta.

#### Scenario: A raw delta ignores residual drift between the two runs

- **WHEN** a report compares the control and loaded runs' corrected percentiles directly, without adding twice `total_uncertainty` before checking against the "meaningfully worse" threshold
- **THEN** report validation rejects the comparison, since the two runs' residual clock errors can differ from each other by up to that amount even within the accepted drift tolerance

#### Scenario: The drift margin is subtracted instead of added for a healthy conclusion

- **WHEN** a report certifies the pipeline as healthy using a delta with the drift margin subtracted rather than added
- **THEN** report validation rejects the certification, since subtracting the margin uses the best-case delta where the worst-case is required to rule out a masked regression

#### Scenario: The raw drift is used instead of total_uncertainty in the delta margin

- **WHEN** a report computes the delta margin as twice the raw largest drift-from-initial value, rather than twice `total_uncertainty` (which also accounts for each drift estimate's own calibration noise)
- **THEN** report validation rejects the margin as understating the true worst-case delta, for the same reason the raw drift value understates `total_uncertainty` elsewhere in this requirement

#### Scenario: A signed drift value understates uncertainty

- **WHEN** a report computes drift as a signed difference between offset estimates and the result is negative, then adds it to uncertainty
- **THEN** report validation rejects the computation, since a negative signed drift would reduce uncertainty instead of accounting for a backward clock adjustment

#### Scenario: A later sample's own noise is omitted from its drift uncertainty

- **WHEN** `total_uncertainty` is computed using only the initial calibration sample's noise plus the largest raw drift value, without adding each later sample's own calibration-noise uncertainty to its drift estimate
- **THEN** report validation rejects the computation, since the later sample's own measurement noise could partially cancel a real clock change and make the observed drift smaller than the true residual error

#### Scenario: The offset is re-estimated per run instead of shared

- **WHEN** a report computes separate clock-offset estimates for the control and loaded runs in the same matched pair, rather than one shared estimate
- **THEN** report validation rejects the pair, since the delta comparison assumes both runs share one offset so uncertainty cancels out of the delta

### Requirement: Lag percentile claims need enough retained samples

A reported lag percentile SHALL meet a sample-count floor and use a pre-registered confidence interval from complete capture windows.

#### Scenario: A percentile is claimed from too few samples

- **WHEN** a report claims a percentile value (e.g. p99) computed from fewer than `1 / (1 − percentile)` retained lag samples
- **THEN** report validation rejects the claim as statistically unreliable

#### Scenario: A bare sample-count floor is treated as a stable estimate

- **WHEN** a report treats a threshold or delta comparison as decisive using only a percentile computed at exactly the `1 / (1 − percentile)` sample-count floor, without a pre-registered confidence interval
- **THEN** report validation rejects the comparison as insufficiently reliable, since a percentile at that floor is effectively the sample maximum

#### Scenario: A straddling confidence interval is treated as decisive

- **WHEN** a percentile's confidence interval straddles the acceptable-lag threshold, or the delta comparison's combined interval straddles the value it is compared against, but a report still treats the comparison as passing
- **THEN** report validation rejects the conclusion; a straddling interval SHALL be treated as a failing comparison, never as evidence of a healthy pipeline

### Requirement: Delta confidence intervals meet the target coverage

A control-to-loaded percentile delta SHALL use Bonferroni-adjusted per-run intervals and account for clock uncertainty.

#### Scenario: An individual run's interval is used as the delta's interval

- **WHEN** a report treats the control or loaded run's own percentile confidence interval as if it were a confidence interval for the difference between the two runs' percentiles
- **THEN** report validation rejects the delta comparison, since an individual run's interval does not bound the uncertainty of a difference between two independent runs

#### Scenario: Per-run intervals are combined without the Bonferroni adjustment

- **WHEN** a report combines the control and loaded runs' percentile confidence intervals for the delta by summing half-widths each computed at the pair's target confidence level, rather than at the higher Bonferroni-adjusted level
- **THEN** report validation rejects the combined interval, since it understates the true joint coverage needed for the pre-registered confidence level

#### Scenario: A corrected lag value ignores its own uncertainty

- **WHEN** a report compares a clock-offset-corrected lag value against the acceptable-lag threshold using the corrected value alone, without adding the recorded offset uncertainty before comparing
- **THEN** report validation rejects the comparison as overstating the precision of a cross-clock measurement

#### Scenario: A confidence interval is compared without clock uncertainty

- **WHEN** a report treats an absolute threshold comparison as decisive using the percentile's confidence interval alone, without expanding it by `total_uncertainty` on both sides before checking whether it straddles the threshold
- **THEN** report validation rejects the comparison, since the confidence interval and `total_uncertainty` capture different sources of error and a percentile whose interval sits entirely below the threshold can still fail once clock-calibration uncertainty is included

### Requirement: Clock drift is monitored across each pair

The benchmark SHALL periodically calibrate the clock offset throughout a pair and reject excessive drift.

#### Scenario: Clock drift during the pair exceeds its tolerance

- **WHEN** the absolute difference between any calibration sample's offset and the pair's initial calibration offset exceeds the pre-registered drift-tolerance bound
- **THEN** report validation rejects the pair, since the reused initial offset may have become stale by that point

#### Scenario: Gradual drift is understated by adjacent-only comparisons

- **WHEN** a report computes drift as the difference between temporally adjacent calibration samples rather than each sample's difference from the initial offset
- **THEN** report validation rejects the computation, since a series of small adjacent shifts can accumulate into a large deviation from the initial offset that adjacent-only comparisons never surface

#### Scenario: A pair omits periodic calibration

- **WHEN** a report presents a matched-pair conclusion with calibration samples only at the start and end of the pair, or fewer samples than the pre-registered cadence requires
- **THEN** report validation rejects the pair for lacking evidence that a transient clock step did not occur and revert between samples

#### Scenario: A report omits the residual undetected-transient limitation

- **WHEN** a report presents a matched-pair conclusion without disclosing the residual limitation that a transient clock step-and-revert entirely between two consecutive calibration samples cannot be detected
- **THEN** report validation rejects the report for claiming completeness this sampling cadence cannot actually provide

### Requirement: Lag conclusions disclose residual limitations

A healthy lag conclusion SHALL state its residual transient-drift and statistical limitations.

#### Scenario: The sampling cadence is not registered relative to the threshold

- **WHEN** a report's calibration sampling cadence is not fixed, before the pair executes, as a pre-registered fraction of the acceptable-lag threshold
- **THEN** report validation rejects the cadence configuration as unbounded relative to the decision it is meant to support

### Requirement: Oversized workloads contain multiple documents

The oversized-result workload SHALL materialize a result that exceeds the entry budget across multiple documents.

#### Scenario: An over-budget result is measured

- **WHEN** a benchmark report claims to measure the cost of admitting an oversized `find`/aggregate result
- **THEN** setup or report validation rejects it unless the workload's result comprises multiple individually-fitting documents whose aggregate encoded size exceeds the configured max-entry size, and the report records the materialization cost paid before rejection

#### Scenario: A single oversized document is mistaken for the required workload

- **WHEN** a workload's oversized result consists of one document whose own encoded size already exceeds the max-entry size
- **THEN** setup or report validation rejects it as the oversized-result workload, since it cannot provide evidence about the cost of materializing many documents before their aggregate crosses the limit

#### Scenario: The oversized-result workload is primed by rejection, not by a hit

- **WHEN** the oversized-result workload completes its warmup
- **THEN** setup verifies a positive delta on the oversized-bypass counter (`stream-cost-observability`) rather than the admission/hit counter deltas required of other cache workload variants

### Requirement: Oversized reports separate end-to-end and encoder cost

The report SHALL distinguish end-to-end materialization time from encoder-invocation time used for savings estimates.

#### Scenario: The end-to-end cost is substituted for an encoder-invocation cost

- **WHEN** a report uses the workload's end-to-end materialization cost (including cursor fetch and transport) as either operand of the incremental-abandonment savings comparison, rather than the two dedicated encoder-invocation-only costs
- **THEN** report validation rejects the substitution, since the end-to-end figure includes time neither admission strategy could ever avoid

#### Scenario: Transport cost is included in the savings comparison

- **WHEN** a report computes the full-result-versus-prefix comparison using total materialization cost (including cursor fetch or network transport) rather than the shipped encoder's invocation cost alone
- **THEN** report validation rejects the comparison as overstating incremental abandonment's possible savings, since transport cost is paid by both strategies regardless

### Requirement: Encoder comparison uses the shipped one-shot encoder

The benchmark SHALL compare repeated shipped-encoder calls on the full result and empirical crossover prefix.

#### Scenario: Full-result cost is claimed without a prefix comparison

- **WHEN** a report claims incremental abandonment is or is not warranted using only the full-result encoder-invocation cost, without the prefix encoder-invocation cost measurement
- **THEN** report validation rejects the claim as lacking the comparison the decision is defined against

#### Scenario: A hypothetical incremental serializer is used instead of the shipped encoder

- **WHEN** a report computes the prefix cost by re-encoding the result under a separate incremental serialization strategy rather than invoking the shipped, unmodified one-shot encoder on the prefix input
- **THEN** report validation rejects the measurement, since it reflects a different envelope and code path than the one this decision concerns

#### Scenario: The shipped encoder is instrumented internally instead of invoked twice

- **WHEN** a report claims a crossover-point measurement obtained by checkpointing or instrumenting state inside the shipped single-shot encode call, rather than invoking that same unmodified encoder separately on a prefix input and the complete input
- **THEN** report validation rejects the measurement, since the shipped encoder has no observable intermediate state to checkpoint

#### Scenario: A single-sample encoder timing is treated as decision evidence

- **WHEN** a report's prefix-versus-full-result encoder-invocation comparison is based on a single timed invocation of either the prefix or the complete result, rather than the pre-registered minimum repetition count aggregated by a pre-registered rule
- **THEN** report validation rejects the comparison as insufficiently reproducible for a decision this consequential

#### Scenario: The crossover prefix is chosen by summing raw document sizes

- **WHEN** a report selects the oversized-result workload's crossover prefix by summing each document's individually pre-computed encoded size, rather than by empirically searching with the shipped encoder's real envelope wrapping
- **THEN** report validation rejects the selection, since array-wrapper and envelope overhead can shift the true crossover point past what the raw sum implies

### Requirement: Savings thresholds are registered before measurement

The benchmark SHALL fix its acceptable encoder-cost saving before taking measurements.

#### Scenario: A savings threshold is chosen after seeing results

- **WHEN** a report sets or adjusts the acceptable-savings threshold between full-result and prefix encoder-invocation cost after observing the oversized-result workload's measurements
- **THEN** report validation rejects the threshold as not pre-registered

### Requirement: Encoder comparisons are triage evidence only

A prefix-versus-full encoder cost comparison SHALL be reported as a prototype triage signal, not a shipping decision.

#### Scenario: A triage signal is treated as conclusive proof either way

- **WHEN** a report concludes incremental abandonment is warranted, or definitively not warranted, directly from the prefix-versus-full-result encoder-invocation comparison, without either a follow-up prototype measurement or an explicit acknowledgment that the negative conclusion is a cost-benefit judgment rather than a proof
- **THEN** report validation rejects the conclusion, since this comparison does not bound a real incremental strategy's cost in either direction — a different encoding approach could cost more or less than this comparison suggests

#### Scenario: A below-threshold result is reported as a judgment, not a proof

- **WHEN** the prefix-versus-full-result encoder-invocation difference does not meet the pre-registered threshold
- **THEN** a report may recommend not prototyping incremental abandonment, but SHALL characterize that recommendation as a cost-benefit judgment about the engineering investment, not as evidence that a real incremental strategy would fail the threshold

### Requirement: Reports preserve per-variant latency distributions

Operation-bearing report rows SHALL retain per-variant sample counts and p50, p95, and p99 latency.

#### Scenario: A report has only aggregate timing

- **WHEN** a benchmark report includes total wall time but lacks per-variant latency distributions associated with cache outcomes
- **THEN** report validation rejects the report as insufficient for an operation-bearing workload's cache cost and benefit conclusions

### Requirement: Idle variants report absent latency samples explicitly

An idle report row SHALL record zero operations and an explicit no-latency-samples marker for each variant.

#### Scenario: An idle report row has no sampled operation

- **WHEN** a controlled workload variant is idle throughout its sampling window
- **THEN** its report row records zero operations and marks latency samples unavailable rather than fabricating percentile values

### Requirement: Proxy measurement identifies its direct path

Optional byte-proxy measurement SHALL count only the direct benchmark path and validate supported connection modes.

#### Scenario: Proxy mode is requested with compression

- **WHEN** a controlled benchmark requests byte-proxy mode with a supported wire compressor on an isolated direct connection
- **THEN** the benchmark counts the bytes crossing that path and identifies the verified negotiated compressor, without presenting those bytes as deployment-wide traffic

#### Scenario: A compressed connection is not established

- **WHEN** a compression comparison requests a compressor that is unavailable or is not negotiated with the server
- **THEN** setup fails rather than recording an uncompressed run under the requested compressor's label

### Requirement: Byte-proxy mode rejects unsupported connections

Byte-proxy mode SHALL reject TLS, topology discovery, and shared-connection configurations that prevent direct-path byte attribution.

#### Scenario: A proxy cannot isolate one direct connection

- **WHEN** a benchmark requests byte-proxy mode with TLS, topology discovery, or a shared connection
- **THEN** setup rejects the configuration before collecting bytes

### Requirement: Compression reports identify uncompressed connections

A report SHALL explicitly label a connection as uncompressed when no wire compressor was negotiated.

#### Scenario: No compressor is requested or negotiated

- **WHEN** a report records a valid uncompressed run
- **THEN** its connection metadata identifies the mode as uncompressed rather than leaving negotiation unspecified

### Requirement: Controlled runs verify cache priming

Controlled cache variants SHALL verify the expected cache outcome before sampling.

#### Scenario: A workload variant is not primed

- **WHEN** a cache workload variant other than the oversized-result workload completes warmup without positive counter deltas for at least one cache admission and one cache hit for that variant
- **THEN** setup or report validation fails before sampled results are accepted

### Requirement: Controlled runs require container CPU

A controlled benchmark SHALL collect MongoDB-container CPU or fail setup.

#### Scenario: Controlled container CPU is unavailable

- **WHEN** a controlled benchmark cannot collect MongoDB-container CPU from its cgroup or runtime
- **THEN** setup fails and the benchmark does not emit a controlled report with an incomplete CPU measurement

### Requirement: Controlled reports include elapsed and process CPU time

Every controlled run SHALL report monotonic wall time and benchmark-process CPU time.

#### Scenario: A controlled report lacks host process timing

- **WHEN** a controlled run omits monotonic elapsed time or benchmark-process CPU time
- **THEN** report validation rejects that run

### Requirement: Controlled timings do not gate across hosts

CI SHALL retain controlled reports as evidence without gating on absolute or cross-host timing.

#### Scenario: A controlled report is slower than a historical report

- **WHEN** a controlled stream-cost report has a larger absolute timing value than a report from another run or host
- **THEN** CI retains the report without failing on that timing difference alone

### Requirement: Compression modes use matched workloads

The benchmark SHALL compare no compression, Snappy, zlib, and Zstandard under matched workloads and topology.

#### Scenario: A four-mode report is produced

- **WHEN** the benchmark completes its comparison
- **THEN** every mode has matched no-stream and stream-watching measurements for the registered workloads, sizes, and repetitions, with counts and order recorded

#### Scenario: A mode silently executes fewer writes

- **WHEN** a run executes or observes fewer operations or change events than its matched schedule requires
- **THEN** report validation rejects that run as incomparable

### Requirement: Compression workloads cover idle and active traffic

The compression matrix SHALL include an idle polling window and active read/write windows with small and large documents.

#### Scenario: A four-mode matrix omits a traffic window

- **WHEN** a comparison lacks idle polling or active read/write measurements for either document size
- **THEN** report validation rejects the matrix as incomplete

### Requirement: Compression reports expose server latency and wire costs

A compression report SHALL include server CPU, latency distributions, and direct-path byte counts for each matched window.

#### Scenario: A report attributes the stream's cost

- **WHEN** a reader compares one compressor's stream-watching path with its no-stream control
- **THEN** the report shows both paths' CPU and direct-path bytes and their difference, while labeling that difference an approximation of the stream's added cost

#### Scenario: An idle window is reported

- **WHEN** a window contains no sampled reads or writes
- **THEN** its CPU and byte measurements remain available and its operation latency is marked unavailable with zero samples

### Requirement: Compression guidance follows retained measurements

Public compressor guidance SHALL follow retained four-mode decision evidence and state workload limits.

#### Scenario: One mode offers a clear trade-off

- **WHEN** repeated measurements support a recommendation under the registered decision rule
- **THEN** the guidance names that mode, links the retained decision evidence, and explains its CPU, latency, and network trade-offs for the library's change-stream workload

#### Scenario: Differences are within measurement noise

- **WHEN** the registered rule cannot distinguish a mode from no compression
- **THEN** guidance keeps no compression as the documented default and labels the result inconclusive rather than claiming a measured win

### Requirement: Compressor recommendations use a defined priority

The recommended PyMongo client compressor setting SHALL prioritize stream-related server CPU and write-to-invalidation latency, then direct-path byte savings.

#### Scenario: A mode saves bytes but costs server time

- **WHEN** a mode reduces bytes but worsens the registered server CPU or invalidation-lag priority
- **THEN** the guidance follows the registered priority and names one measured client setting with its trade-offs

### Requirement: Compression guidance leaves client configuration under caller control

The benchmark and guidance SHALL NOT change the public cache API or silently override the caller's PyMongo client compressor setting.

#### Scenario: A caller chooses a compressor independently

- **WHEN** a caller configures a PyMongo client with a compressor other than the documented recommendation
- **THEN** the cache uses that client without rewriting its compressor configuration

### Requirement: Reports surface an explicit change-stream CPU-cost comparison

For the `BALANCED` workload (concurrent insert and read traffic) at each configured data size, a controlled report SHALL present a raw-path and cache-path `container_cpu_seconds` value side by side as an explicit change-stream CPU-cost comparison, since the cache path watches a change stream and the raw path does not.

#### Scenario: A controlled report includes the BALANCED workload

- **WHEN** a controlled report includes the `BALANCED` workload
- **THEN** the report presents the raw path's and cache path's `container_cpu_seconds` values side by side as the change-stream CPU-cost comparison

### Requirement: Reports surface an explicit change-stream network-cost comparison when byte-proxy mode is enabled

When the report was produced with `--direct-path-proxy` enabled, it SHALL present the raw-path and cache-path `direct_path_bytes_sent`/`direct_path_bytes_received` values side by side as an explicit change-stream network-cost comparison.

#### Scenario: The report was generated with byte-proxy mode enabled

- **WHEN** the report was generated with `--direct-path-proxy`
- **THEN** it also presents the raw path's and cache path's `direct_path_bytes` values side by side as the change-stream network-cost comparison

### Requirement: The network-cost comparison is marked unavailable without byte-proxy mode

Absent `--direct-path-proxy`, the report SHALL note the network-cost comparison as unavailable for that run rather than omitting it silently.

#### Scenario: The report was generated without byte-proxy mode

- **WHEN** the report was generated without `--direct-path-proxy`
- **THEN** the network-cost comparison is explicitly marked unavailable for that run, not silently omitted

### Requirement: Change-stream resource comparisons state path scope

Reports SHALL identify that each path value includes its full run and that the path difference approximates added stream cost.

#### Scenario: A report explains what the comparison values cover

- **WHEN** a controlled report includes the change-stream resource-cost comparison
- **THEN** the report documents that each path's value covers that path's whole run, and that the difference between the two paths - not either value alone - approximates the change stream's added cost

### Requirement: Await-time candidates use matched workload windows

The benchmark SHALL compare 1,000 ms with multiple larger await times under matched idle and relevant-write workloads, repeated in counterbalanced order with fresh state.

#### Scenario: An idle candidate is measured

- **WHEN** the benchmark samples a candidate during a window with no application reads or writes
- **THEN** its report contains actual `getMore` counts and resource measures for that window, with no operation-latency samples

#### Scenario: Candidate workloads differ

- **WHEN** candidate runs differ in event schedule, stream count, topology, or measurement scope
- **THEN** report validation rejects their comparison as evidence for a default

### Requirement: Await-time reports record wire commands and costs

The benchmark SHALL record actual `getMore` counts and requested `maxTimeMS`, server and client CPU, direct bytes, event counts, invalidation lag, and shutdown duration for both execution models.

#### Scenario: A worker-loop count substitutes for wire commands

- **WHEN** a report uses the manager's `stream_polls` counter as its count of actual `getMore` commands
- **THEN** report validation rejects that count

#### Scenario: A required measure is missing

- **WHEN** a candidate lacks a required matched wire, CPU, byte, event, lag, or shutdown measure
- **THEN** report validation rejects that candidate comparison

### Requirement: Await-time reports state topology scope

The report SHALL distinguish measurements on the tested replica set from unmeasured sharded-cluster behavior.

#### Scenario: A report generalizes beyond its topology

- **WHEN** results measured on a replica set are described as covering sharded clusters
- **THEN** report validation rejects that unsupported claim

### Requirement: Await-time decisions use a frozen configuration

The benchmark SHALL freeze candidate workloads, metrics, uncertainty rules, limits, and selection criteria before sampling and retain the configuration hash with results.

#### Scenario: A rule is chosen after sampling

- **WHEN** a report uses thresholds or candidate-ranking criteria not fixed before sampling
- **THEN** it cannot support a new default recommendation

#### Scenario: A frozen configuration omits decision inputs

- **WHEN** the pre-run configuration lacks candidate values, repetitions, durations, write schedules, confidence-interval method, multiplicity adjustment, noise treatment, or latency and shutdown limits
- **THEN** the report cannot use that configuration to justify a selected default

### Requirement: Await-time defaults meet registered limits

A selected await-time default SHALL meet registered lag, active server and client CPU, idle client CPU, and shutdown limits, then show decisive idle server CPU or direct-byte savings in both execution models.

#### Scenario: A larger value meets the rule

- **WHEN** repeated measurements show a candidate's resource benefit beyond the registered noise threshold while its latency and shutdown results meet the registered limits
- **THEN** the decision evidence selects the qualifying candidate with the lowest measured resource cost according to the registered ranking rule

### Requirement: Await-time candidates follow the registered ranking

Eligible candidates SHALL be ranked by their worse resource result across sync and asyncio paths: decisive idle server CPU reduction in both paths first, then decisive direct-byte reduction in both, then the shorter wait when unresolved.

#### Scenario: Two eligible candidates offer different resource savings

- **WHEN** candidate outcomes satisfy the registered safety limits
- **THEN** the decision applies the CPU, byte, and shorter-wait tie-breaks in that order across both execution models

### Requirement: Await-time evidence retains every candidate outcome

The report SHALL retain each candidate's decision evidence, including failed and inconclusive comparisons, together with the configuration hash, repository revision, and environment.

#### Scenario: A candidate does not qualify

- **WHEN** a candidate fails a registered limit or its improvement is inconclusive after adjustment for all candidate and workload comparisons
- **THEN** its evidence remains in the report and cannot be omitted from the decision

#### Scenario: Commit reproducible evidence as a summary

- **WHEN** benchmark evidence is added to source control
- **THEN** a prose Markdown summary records every candidate outcome, failures, limitations, configuration hash, revision, environment, and reproduction commands
- **AND** raw results remain untracked, with only a genuinely useful reproduction configuration under 200 lines retained as JSON

### Requirement: Inconclusive await-time comparisons retain the default

Measurement noise SHALL NOT justify changing the 1,000 ms default; public guidance SHALL state the evidence and limitations.

#### Scenario: Results are inconclusive

- **WHEN** candidates cannot be distinguished reliably or all larger values violate the registered limits
- **THEN** the decision evidence retains 1,000 ms, labels the result accordingly, and makes no claim of a measured improvement

### Requirement: Public await-time guidance cites the selected evidence

Public guidance SHALL name the selected value, link retained evidence, explain resource and responsiveness trade-offs, and state topology and PyMongo timeout limits without claiming an unmeasured universal optimum.

#### Scenario: A default is published

- **WHEN** the library documents its chosen `max_await_time_ms`
- **THEN** readers can find the measured rationale, committed summary, trade-offs, and the limits of the tested environment
