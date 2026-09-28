# stream-cost-benchmarking Specification

## Purpose

This capability provides controlled, reproducible workload reports for the cost and benefit of change-stream-backed local caching.

## Requirements

### Requirement: Benchmarks compare equivalent workloads

The benchmark suite SHALL compare raw and coherent-cache variants with identical seeded data, query shapes, read/write mixes, concurrency, duration, warmup, and sample schedules. Before sampling each workload variant, including each workload/data-size combination, the cache variant SHALL run its configured warmup through the normal coherent-cache admission path and SHALL verify positive counter deltas for at least one cache admission and one cache hit for that variant, except for the oversized-result workload (see "Oversized-result workloads measure over-budget materialization cost"), whose result is designed to exceed the max-entry size and be discarded rather than admitted — that workload SHALL instead verify a positive delta on `stream-cost-observability`'s labelled oversized-bypass counter before sampling. The benchmark SHALL fail setup or report validation when a sampled variant lacks its required counter deltas. Every report row SHALL identify the corresponding warmup counter deltas, and every report SHALL identify revision, versions, topology, resource limits, workload parameters, samples, and limitations.

#### Scenario: A paired workload is reported

- **WHEN** a benchmark writes a raw-versus-cache comparison report
- **THEN** the validator rejects it if either variant lacks a required matching workload parameter

### Requirement: Consolidated-stream workloads cover topology and traffic

For measurements intended to characterize the consolidated database-scoped stream, the workload matrix SHALL configure exactly one database-scoped stream serving at least two cached collections in the same database. It SHALL separately identify writes to measured cached collections whose events can invalidate the measured entries and writes to collections outside the measured cached set but in that same database. The workload parameters and report SHALL record the exact stream count, collection-to-stream mapping, and the counts or rates for relevant and unrelated writes.

#### Scenario: A consolidated stream is characterized

- **WHEN** a benchmark report claims to measure the cost of one database-scoped stream across cached collections
- **THEN** setup or report validation rejects it unless exactly one stream serves at least two cached collections in one database, the unrelated writes target collections in that same database, and the report records its collection-to-stream mapping plus both relevant and unrelated write traffic

### Requirement: Consolidated-stream conclusions require a matched control

A report SHALL NOT attribute an invalidation-lag change to unrelated write traffic unless it includes a matched pair of consolidated-stream runs: one with unrelated-collection writes disabled and one with the same relevant-write traffic plus unrelated writes enabled. Both runs in a pair SHALL otherwise share identical workload parameters, and both SHALL process a positive count of relevant writes and record at least the minimum sample count required by the pre-registered percentile (see "Invalidation-lag comparisons use a calibrated, pre-registered threshold") in their invalidation-lag distribution; a run with an empty or under-sampled distribution SHALL fail setup or report validation rather than being treated as evidence for either branch of the conclusion. Matching relevant-write count or rate alone is not sufficient: invalidation lag is sensitive to write spacing and queueing bursts, not only to aggregate volume, so two runs with the same total count but different burst timing (e.g. evenly spaced versus front-loaded) are not comparable even if their counts match. The workload configuration SHALL therefore generate one fixed, deterministic relevant-write schedule — an explicit sequence of write-issue offsets relative to run start — before the pair executes, and both runs SHALL replay that identical schedule, each write issued within a small, pre-registered per-write timing tolerance of its scheduled offset; a report SHALL NOT independently generate relevant-write timing per run, even to the same target count or rate, and SHALL NOT substitute an aggregate count/rate check for verifying the schedule was actually followed. The loaded run SHALL additionally process at least a pre-registered minimum count or rate of unrelated writes, fixed in the workload configuration before the pair executes — not merely a positive count, since a loaded run satisfying "more than zero" with, say, a single unrelated write does not exercise the heavy unrelated traffic this workload is meant to characterize any more than the control run does, and would let a no-bottleneck conclusion pass without ever meaningfully loading the pipeline. Enabling the unrelated writer is not sufficient on its own; the actual observed count or rate SHALL meet the pre-registered minimum, and this minimum SHALL be met by unrelated writes that temporally overlap the window during which relevant-write invalidation-lag samples are being collected, not merely occurring at some point during the run (e.g. entirely during warmup) — a loaded run whose unrelated writes do not overlap the sampled interval never actually subjects the measured samples to concurrent unrelated load. Each run in a pair SHALL start from an equivalent, reset starting state — freshly seeded database contents, an empty cache, and a stream cursor opened fresh for that run — rather than reusing the database, cache, or stream state a prior run in the same pair left behind; a report SHALL NOT run the control and loaded variants of a pair sequentially against shared, un-reset state, since the second run's document contents, index state, or cache occupancy would then differ from the first's for reasons unrelated to unrelated-write traffic. Resetting the database, cache, and stream cursor does not reset the underlying replica-set server's own state — WiredTiger cache contents, the OS page cache, and the oplog window can all remain "warmer" for whichever run executes second on the same server instance, independent of unrelated-write treatment. A report SHALL therefore run both runs in a pair against the same replica-set topology — never a freshly provisioned topology per run, which would also invalidate "Invalidation-lag comparisons use a calibrated, pre-registered threshold"'s single shared clock-offset calibration: a different topology means a different primary, whose clock offset the pair's one reused calibration was never estimated against — and SHALL counterbalance run order across repeated pairs (alternating which variant runs first) and apply an explicit, pre-registered warm-up phase before each run's sampling window begins, bringing server-side caches to a comparable steady state before either run is sampled. A report using a single, non-counterbalanced run order SHALL NOT attribute an observed lag difference to unrelated-write traffic alone. Counterbalancing requires more than one pair, and a single pair's within-pair confidence intervals — however correctly constructed — cannot estimate variation between repeated executions of the same pair (server cache state, exact burst timing, and other run-level conditions that persist across a pair's two runs but vary from one pair to the next). The benchmark configuration SHALL therefore fix a pre-registered minimum number of repeated, counterbalanced pairs (e.g. at least three) before any run executes. Task 5.1's "not meaningfully worse" (healthy) conclusion SHALL be certified only if every pair in that pre-registered set independently satisfies "Invalidation-lag comparisons use a calibrated, pre-registered threshold"'s branch-(a) condition — one pair passing while another fails SHALL be treated as an overall failure, the same conservative default used for every other undecidable case here, not averaged or overridden by a majority. The report SHALL record both runs' clock-offset-corrected invalidation-lag distributions (see "Invalidation-lag comparisons use a calibrated, pre-registered threshold") side by side. A report SHALL NOT conclude the delivery pipeline is healthy from a flat control-to-loaded delta alone: both the control run's and the loaded run's own absolute lag distributions SHALL also meet the pre-registered acceptable-lag threshold. Checking the delta and the control's absolute lag is not sufficient by itself either — a permissive "meaningfully worse" rule could let a loaded run that itself exceeds the threshold still count as not meaningfully worse than an already-marginal control. This comparison measures the end-to-end delivery pipeline under load — server processing, transport, and router dispatch combined — not router-internal serialization time in isolation; a report SHALL NOT claim the lag delta isolates router CPU time or router queueing specifically, only that the shipped pipeline as a whole is or is not measurably slower to invalidate under this traffic pattern.

#### Scenario: A router-lag conclusion lacks a control

- **WHEN** a report attributes an invalidation-lag increase to unrelated write traffic using only a single loaded consolidated-stream run
- **THEN** report validation rejects the conclusion for lacking the matched unrelated-writes-disabled control run

#### Scenario: A report over-claims router-only attribution

- **WHEN** a report attributes an end-to-end invalidation-lag increase specifically to router-internal serialization rather than to the delivery pipeline as a whole
- **THEN** report validation rejects the claim, since this workload does not instrument router-internal stage timing separately from server and transport time

#### Scenario: A saturated baseline is mistaken for a healthy pipeline

- **WHEN** a report concludes the delivery pipeline is not a bottleneck using only a flat control-to-loaded lag delta, without checking both runs' absolute lag against the pre-registered threshold
- **THEN** report validation rejects the conclusion, since a pipeline already saturated by relevant traffic alone would show the same flat delta

#### Scenario: A run reuses a prior run's mutated state

- **WHEN** a matched pair's control and loaded runs execute sequentially against the same database, cache, and stream without resetting between them
- **THEN** setup or report validation rejects the pair, since a lag difference could then be caused by carried-over document or cache state rather than unrelated write traffic

#### Scenario: A pair runs on a fixed order without warm-up

- **WHEN** a report runs a pair's two runs on the same replica-set topology without counterbalancing run order across repeated pairs or applying a pre-registered warm-up phase before each run
- **THEN** report validation rejects the attribution of any observed lag difference to unrelated-write traffic, since server-side cache warmth could differ between the runs independent of that traffic

#### Scenario: A healthy conclusion is certified from a single pair

- **WHEN** a report certifies the pipeline as healthy using only one pair's result, without the pre-registered minimum number of repeated, counterbalanced pairs
- **THEN** report validation rejects the certification, since a single pair cannot distinguish within-pair sampling variance from variation between repeated executions

#### Scenario: One failing pair is overridden by passing pairs

- **WHEN** a report certifies the pipeline as healthy because a majority (but not all) of the pre-registered set of repeated pairs independently satisfy branch (a)'s condition
- **THEN** report validation rejects the certification; any pair failing to satisfy branch (a) makes the overall result a failure, not an average or a majority vote

#### Scenario: A pair uses a fresh topology per run

- **WHEN** a report provisions a separate replica-set topology for each run in a matched pair
- **THEN** report validation rejects the pair, since the two runs would then have different primaries and the pair's single shared clock-offset calibration was never estimated against the second run's server

#### Scenario: A run has no relevant invalidations to sample

- **WHEN** a control or loaded consolidated-stream run completes with zero relevant writes processed or a lag-sample count below the pre-registered percentile's minimum
- **THEN** setup or report validation fails that run rather than allowing an empty or under-sampled distribution into a healthy-pipeline conclusion

#### Scenario: The loaded run falls short of the minimum unrelated-write load

- **WHEN** a loaded consolidated-stream run completes with its unrelated writer enabled but its observed unrelated-write count or rate falls below the pre-registered minimum
- **THEN** setup or report validation fails that run, since a below-minimum load does not meaningfully exercise the traffic pattern this workload is meant to characterize

#### Scenario: Unrelated writes do not overlap the sampling window

- **WHEN** a loaded run's unrelated writes meet the pre-registered minimum count or rate in total, but occur entirely outside the window during which relevant-write invalidation-lag samples are collected (e.g. only during warmup)
- **THEN** setup or report validation fails the run, since the sampled invalidations were never actually subjected to concurrent unrelated load

#### Scenario: Relevant-write load differs between the control and loaded runs

- **WHEN** the control and loaded runs' observed relevant-write counts or rates fall outside the pre-registered tolerance of each other
- **THEN** setup or report validation fails the pair, since a difference in relevant traffic alone can change invalidation lag independently of unrelated writes and contaminate the comparison

#### Scenario: Matching counts substitute for a replayed schedule

- **WHEN** the control and loaded runs independently generate relevant writes at the same target count or rate, rather than each replaying the pair's one fixed, pre-registered write-issue schedule
- **THEN** setup or report validation fails the pair, since burst timing can differ between the runs even when aggregate counts match, and invalidation lag is sensitive to that timing

#### Scenario: A permissive delta rule masks a loaded-run failure

- **WHEN** a report concludes the delivery pipeline is healthy because the loaded run is not "meaningfully worse" than the control, while the loaded run's own absolute lag exceeds the pre-registered threshold
- **THEN** report validation rejects the conclusion, since the delta rule alone does not guarantee the loaded run itself is within the acceptable-lag threshold

### Requirement: Invalidation-lag comparisons use a calibrated, pre-registered threshold

A change event's `wallTime` is recorded by the specific `mongod` that originated it — in a replica set, the primary that accepted the write at that time — so the clock offset SHALL be estimated against that same server, not an arbitrary member of the set. Before any run in a matched control/loaded pair executes, the benchmark SHALL estimate the clock offset between the benchmark host and the replica set's current primary (the server the consolidated stream is reading events from) once and reuse that single estimate for both runs in the pair (never re-estimated independently per run). The shared offset's calibration-noise uncertainty cancels out of the control-versus-loaded delta only if the true offset stayed exactly constant across the interval; since a nonzero drift tolerance is accepted below, the two runs' actual residual errors can differ from each other by up to twice `total_uncertainty` (defined below — the drift-and-its-own-noise upper bound, not the raw observed drift alone), one run's true offset having drifted one way and the other's the opposite way relative to the reused initial estimate — this residual difference does not cancel and SHALL also be accounted for in the delta comparison, not only in absolute-threshold comparisons. The benchmark SHALL monitor primary identity for the entire calibration-to-pair interval — from the moment calibration is sampled through the completion of both runs in the pair, not only while a given run is executing, since an election between the control and loaded runs would leave the loaded run's events originating from a different server than the one calibration was performed against. The driver's topology-changed events are one signal but not sufficient on their own: the driver's heartbeat-based topology monitoring can lag the server's actual election by up to a heartbeat interval, so a stepdown-and-new-election could complete, and even be reported as a topology event, only after some events have already been served by the new primary while the benchmark still treats the old calibration as valid. The benchmark SHALL therefore also record each periodic `hello` calibration sample's `electionId` (a value that changes on every election, including a stepdown-and-return to the same node) alongside its `localTime`, and SHALL treat a change in `electionId` between any two calibration samples the same as a primary change reported via topology events — failing the entire pair. This closes the interval between calibration polls (bounded by the same pre-registered cadence already fixed for drift sampling) rather than depending solely on the driver noticing and reporting the change; it does not close the residual gap of an election-and-reversion occurring entirely between two calibration polls, which carries the same disclosed-assumption treatment as the clock-step gap below. If a primary change is detected by either mechanism anywhere in the interval, the benchmark SHALL fail the entire pair's report validation (not merely the run in progress at the time) rather than continue applying an offset calibrated against a server that is no longer, or was not yet, the stream's event source for both runs. It SHALL sample the primary's `hello` command `localTime` field over a bounded number of round trips: for each sample, `t0` is the local time the request was sent, `t1` is the local time its response was received, and `T_s` is the `localTime` value in that response; the benchmark SHALL select the sample with the minimum `(t1 − t0)` round-trip time and compute the offset as `offset = T_s − (t0 + t1) / 2` (a positive offset means the server clock reads ahead of the host clock), per the standard minimum-round-trip-time clock-offset technique — minimizing the contribution of network jitter versus a single uncalibrated sample. `t0`, `t1`, and the local invalidation-apply timestamp `A` SHALL all be read from the benchmark host's wall clock (e.g. a UTC-based timestamp), never a monotonic clock — a monotonic clock has an arbitrary, implementation-defined epoch unrelated to wall-clock time, so subtracting a monotonic reading from the server's wall-clock `wallTime` would produce a meaningless value regardless of how the offset was calibrated. This is distinct from, and does not conflict with, this benchmark's requirement to use a monotonic clock for elapsed-duration measurements (e.g. operation latency, encoder-invocation timing) elsewhere: those measure a duration entirely on the benchmark host and correctly prefer monotonic time's immunity to clock adjustments, while this lag calculation inherently compares two different clocks and requires both readings to be on the same wall-clock basis to be meaningful at all. Because the benchmark host's own wall clock can itself be stepped or slewed during the interval (e.g. by its NTP daemon) independent of anything happening on the server — a change the primary-drift monitoring above cannot detect, since it only tracks the server's offset relative to the host, not the host's own clock stability — the benchmark SHALL sample a monotonic clock reading alongside every wall-clock reading of `A`, `t0`, and `t1`, and SHALL compare the elapsed monotonic duration against the elapsed wall-clock duration between any two such paired readings; if they diverge by more than a small pre-registered tolerance, the benchmark SHALL treat this as evidence the host's wall clock was adjusted during the interval and SHALL invalidate the pair, the same way a primary change invalidates it. For an event with projected server `wallTime` `W`, and the wall-clock invalidation-apply timestamp `A`, the corrected invalidation delivery lag SHALL be computed as `(A − W) + offset`. Both `hello.localTime` and the event's projected `wallTime` are BSON Date values quantized to whole milliseconds; when the selected round trip's own duration is comparable to or smaller than this resolution, half the round-trip time alone does not bound the error, since quantization on `T_s`, `W`, and `A` each contributes independently. The benchmark SHALL record the offset's own calibration-noise uncertainty as half the selected sample's round-trip time plus one millisecond (a conservative bound covering quantization on both the calibration sample's `T_s` and any BSON Date timestamp compared against it) — a low round trip is not itself a failure condition (the dedicated local benchmark topology's loopback or container networking commonly produces round trips at or below this resolution, and a low round trip is the best-case calibration scenario, not a degraded one); it simply means the resulting uncertainty is quantization-dominated rather than jitter-dominated, and the millisecond allowance already accounts for that. Because a single calibration sample does not bound clock drift or a clock step (e.g. an NTP correction) occurring during the interval between calibration and either run, the benchmark SHALL sample the same primary's `hello.localTime` repeatedly throughout the interval at a fixed, pre-registered cadence — at minimum at the start, between the control and loaded runs, and at the end — rather than only at the start and end, since a transient step that reverts before the end-of-pair sample would otherwise leave the start-versus-end difference at or near zero despite having shifted lag measurements while it was in effect. Every calibration sample, not only the initial one, carries its own calibration-noise uncertainty computed identically — half that sample's selected minimum round-trip time plus the same one-millisecond BSON Date quantization allowance — since every `hello.localTime` sample is subject to the same millisecond quantization regardless of when during the pair it was taken; a later sample's uncertainty is never computed as half its round trip alone. For every sample taken after the initial one, the benchmark SHALL compute a drift estimate as the absolute value of the difference between that sample's offset and the initial calibration offset — never an adjacent-to-adjacent difference, which understates cumulative drift for a gradually drifting clock (e.g. ten successive 1ms adjacent-to-adjacent shifts would each individually look small while the initial offset, the one actually reused for the whole pair's corrections, has become stale by 10ms), and never a signed difference, since a backward clock adjustment would otherwise produce a negative value that both passes a tolerance check meant to catch large drift and, if added directly to uncertainty, shrinks it instead of accounting for it. Each drift estimate SHALL itself carry a combined uncertainty equal to the initial sample's calibration-noise uncertainty plus that later sample's own calibration-noise uncertainty (not the initial sample's alone) — a later sample's own measurement noise can partially cancel a real clock change in the raw difference, making the observed drift value smaller than the true residual correction error, so omitting that sample's own noise from its drift estimate's uncertainty would understate the risk rather than bound it. The pre-registered configuration SHALL fix a drift-tolerance bound before the pair executes; if any sample's drift-from-initial estimate exceeds it, the benchmark SHALL treat the entire pair as invalid rather than apply an offset that may have shifted during the interval. Discrete periodic sampling has an irreducible residual limitation this benchmark cannot fully close: a transient step-and-revert occurring entirely between two consecutive calibration samples is invisible to every drift check described above, no matter how the samples are combined — and unlike the sampling cadence, which bounds how long such a step could remain undetected, this benchmark has no way to bound the step's magnitude, since it was never observed; `total_uncertainty` therefore cannot be said to account for it at all, only for drift the calibration samples actually captured. The benchmark configuration SHALL fix the sampling cadence itself as a pre-registered fraction of the acceptable-lag threshold (e.g. cadence period ≤ threshold / 10) to bound the exposure window, but a "not meaningfully worse" (healthy) conclusion from task 5.1 SHALL be reported together with an explicit, disclosed assumption — not a proven bound — that no clock step-and-revert occurred entirely between two consecutive calibration samples during the pair; this benchmark's instrumentation cannot verify that assumption, only make its violation less likely by sampling frequently. A report SHALL NOT present a healthy conclusion as fully verified against this failure mode. The total uncertainty used in comparisons SHALL be the largest observed (drift estimate + that drift estimate's own combined uncertainty) across all samples — not the initial sample's calibration-noise uncertainty alone plus the largest raw drift value, which would omit each later sample's own measurement noise — and a value's comparison against the acceptable-lag threshold SHALL use `value + total_uncertainty` (the conservative, worst-case-corrected reading), never the uncorrected `value` alone — a comparison that would only pass using the uncorrected value SHALL be treated as not meeting the threshold. Separately, before any run in a pair executes, the benchmark configuration SHALL fix both an acceptable-lag threshold (a specific percentile, e.g. p99, and its maximum acceptable corrected-lag value) and the comparison rule defining "meaningfully worse" between the control and loaded runs, computed on the two runs' corrected percentile values with a conservative drift margin ADDED to the observed delta before comparing against the threshold: `(loaded_percentile − control_percentile) + 2 × total_uncertainty`, using twice `total_uncertainty` as defined above (the drift-and-its-own-noise upper bound, not the raw observed drift alone — using the raw drift here would repeat the same understatement risk `total_uncertainty` was defined to close), since the two runs could have drifted in opposite directions relative to the shared initial offset by up to that amount each. Addition, not subtraction, is the conservative direction here: this comparison is used to certify the pipeline as healthy (branch (a) of task 5.1), so the check must use the worst-case (largest plausible) true delta, not the best-case — subtracting the margin would instead make it easier to reach a "not meaningfully worse" conclusion precisely when residual drift could be masking a real regression, which is the failure mode this whole calibration apparatus exists to prevent. The pipeline is treated as "not meaningfully worse" only if this drift-inflated delta stays at or below the threshold; if it exceeds the threshold, the comparison does not conclude the pipeline is unhealthy either — it is simply insufficient to certify health, routing to branch (b) the same as an outright failure would. This comparison rule SHALL be an absolute increase (e.g. the loaded run's percentile exceeds the control's by more than a fixed duration), never a percentage or ratio: the shared additive offset cancels out of an absolute difference between the two runs' corrected values (up to the drift margin above), but does not cancel out of a ratio at all — `(loaded + offset) / (control + offset)` is not independent of `offset` the way `(loaded + offset) − (control + offset)` is — so a percentage-based rule would classify the same pair differently depending on an offset the benchmark cannot know exactly, defeating the point of sharing one calibration across both runs. A report SHALL NOT set or adjust either the threshold or the comparison rule after observing run results; it SHALL record the pre-run configuration alongside the observed outcome. A percentile claimed from the bounded lag distribution (`stream-cost-observability`) requires at least `1 / (1 − percentile)` retained samples merely for the percentile to be defined at all (e.g. p99 requires at least 100 samples) — this is an absolute floor, not evidence of a stable estimate: at exactly this floor, the percentile is effectively the sample maximum and carries enormous estimation variance, unfit to gate an architectural decision on its own. The benchmark configuration SHALL therefore also fix, before sampling, a pre-registered confidence level (e.g. 95%) and require the report to compute a confidence interval for the percentile using a block bootstrap that resamples, with replacement, among `stream-cost-observability`'s pre-registered capture windows — each window's complete, gap-free set of retained events used in its entirety as one bootstrap block — rather than a method that assumes independent observations or that defines its own block size cut across a distribution with no guaranteed contiguity. Invalidation-lag samples from a single serial router can be dependent in ways a simpler check cannot rule out; resampling whole captured windows is used specifically because it remains valid without needing that dependence structure characterized in advance, and because each window is genuinely contiguous by construction. Capture windows are defined by a fixed event count, not a fixed duration (`stream-cost-observability`), so all windows are the same size; the block bootstrap SHALL draw windows uniformly (each window equally likely, never weighted by size or any other criterion) — this is the standard, correctly-calibrated construction for equal-size blocks, and weighting selection probability by size while also including a block's full content would double-count large blocks quadratically rather than represent them proportionally. The confidence interval (capturing sampling/statistical uncertainty in the percentile estimate) and `total_uncertainty` (capturing clock-calibration uncertainty) are different, non-overlapping sources of error, and a report SHALL combine both before any threshold comparison, never substituting one for the other: it SHALL construct a combined interval by adding `total_uncertainty` to the confidence interval's upper bound and subtracting `total_uncertainty` from its lower bound. A report SHALL treat an absolute threshold comparison as decisive only if this combined interval — the confidence interval, computed at the pre-registered confidence level (1 − α), expanded by `total_uncertainty` on both sides — does not straddle the acceptable-lag threshold. For the drift-adjusted delta comparison, an individual run's own-level confidence interval is not itself a valid (1 − α) confidence interval for the difference between two independent runs' percentiles, and naively summing two half-widths each computed at level (1 − α) understates the combined interval's true coverage (for independent intervals, their naive combination achieves only roughly (1 − α)² joint coverage, not (1 − α)). The benchmark SHALL instead apply a Bonferroni correction: compute each run's own percentile confidence interval at the higher confidence level (1 − α/2), not the pair's target level (1 − α), then sum those two intervals' half-widths to obtain the delta interval's half-width, centered on the drift-adjusted delta itself — this guarantees the combined interval's coverage is at least the pre-registered (1 − α) level for the difference, by the union bound. A report SHALL treat the delta comparison as decisive only if this Bonferroni-combined interval does not straddle the acceptable-lag threshold it is being compared against. If either interval straddles the value it is compared against, that comparison is inconclusive and SHALL be treated the same as a failing comparison for task 5.1's purposes — the conservative direction, since an inconclusive result must not be read as evidence of a healthy pipeline. A report SHALL NOT claim a percentile value, or treat a threshold or delta comparison as decisive, without meeting the sample-count floor and the appropriate confidence-interval requirement above.

#### Scenario: Clock offset is estimated by minimum round-trip time

- **WHEN** the benchmark estimates the server-host clock offset
- **THEN** it samples the current primary's `hello` command `localTime` over multiple round trips, selects the minimum-round-trip-time sample for the offset estimate, and records half that sample's round-trip time plus one millisecond of BSON Date quantization allowance as the uncertainty bound

#### Scenario: The quantization allowance is omitted from a low round-trip calibration

- **WHEN** a report computes calibration-noise uncertainty as half the selected round-trip time alone, without the one-millisecond BSON Date quantization allowance — most consequential for a low round trip, where quantization rather than jitter dominates the true error, but required regardless of round-trip magnitude
- **THEN** report validation rejects the uncertainty computation as omitting a required error source, though a low round trip itself is not rejected

#### Scenario: A later calibration sample omits the quantization allowance

- **WHEN** a report computes a non-initial calibration sample's own uncertainty as half its round-trip time alone, without the one-millisecond quantization allowance applied to the initial sample
- **THEN** report validation rejects the drift estimate's uncertainty as inconsistent, since every calibration sample is subject to the same BSON Date quantization regardless of its position in the sequence

#### Scenario: A monotonic clock is used for a cross-clock measurement

- **WHEN** the benchmark records `t0`, `t1`, or the invalidation-apply timestamp `A` using a monotonic clock rather than a wall clock
- **THEN** report validation rejects the corrected-lag computation, since a monotonic reading cannot be meaningfully compared against the server's wall-clock `wallTime`

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

#### Scenario: A threshold is fixed before sampling

- **WHEN** a report includes an acceptable-lag threshold or a "meaningfully worse" comparison rule
- **THEN** report validation rejects it unless that threshold and rule were part of the pre-run configuration, not chosen after observing results

#### Scenario: A percentage-based comparison rule is used

- **WHEN** a report's "meaningfully worse" comparison rule expresses the control-to-loaded change as a percentage or ratio rather than an absolute difference
- **THEN** report validation rejects the rule, since the shared clock-offset uncertainty does not cancel out of a ratio the way it cancels out of an absolute difference

#### Scenario: A raw delta ignores residual drift between the two runs

- **WHEN** a report compares the control and loaded runs' corrected percentiles directly, without adding twice `total_uncertainty` before checking against the "meaningfully worse" threshold
- **THEN** report validation rejects the comparison, since the two runs' residual clock errors can differ from each other by up to that amount even within the accepted drift tolerance

#### Scenario: The drift margin is subtracted instead of added for a healthy conclusion

- **WHEN** a report certifies the pipeline as healthy using a delta with the drift margin subtracted rather than added
- **THEN** report validation rejects the certification, since subtracting the margin uses the best-case delta where the worst-case is required to rule out a masked regression

#### Scenario: The raw drift is used instead of total_uncertainty in the delta margin

- **WHEN** a report computes the delta margin as twice the raw largest drift-from-initial value, rather than twice `total_uncertainty` (which also accounts for each drift estimate's own calibration noise)
- **THEN** report validation rejects the margin as understating the true worst-case delta, for the same reason the raw drift value understates `total_uncertainty` elsewhere in this requirement

#### Scenario: A percentile is claimed from too few samples

- **WHEN** a report claims a percentile value (e.g. p99) computed from fewer than `1 / (1 − percentile)` retained lag samples
- **THEN** report validation rejects the claim as statistically unreliable

#### Scenario: A bare sample-count floor is treated as a stable estimate

- **WHEN** a report treats a threshold or delta comparison as decisive using only a percentile computed at exactly the `1 / (1 − percentile)` sample-count floor, without a pre-registered confidence interval
- **THEN** report validation rejects the comparison as insufficiently reliable, since a percentile at that floor is effectively the sample maximum

#### Scenario: A straddling confidence interval is treated as decisive

- **WHEN** a percentile's confidence interval straddles the acceptable-lag threshold, or the delta comparison's combined interval straddles the value it is compared against, but a report still treats the comparison as passing
- **THEN** report validation rejects the conclusion; a straddling interval SHALL be treated as a failing comparison, never as evidence of a healthy pipeline

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

#### Scenario: A healthy conclusion is presented as a proven bound

- **WHEN** a report presents task 5.1's "not meaningfully worse" (healthy) conclusion without disclosing that it depends on the unverifiable assumption that no clock step-and-revert occurred between consecutive calibration samples
- **THEN** report validation rejects the conclusion for claiming a guarantee this benchmark's instrumentation cannot provide, since an undetected step's magnitude — unlike its possible duration — is not bounded by the sampling cadence

#### Scenario: The sampling cadence is not registered relative to the threshold

- **WHEN** a report's calibration sampling cadence is not fixed, before the pair executes, as a pre-registered fraction of the acceptable-lag threshold
- **THEN** report validation rejects the cadence configuration as unbounded relative to the decision it is meant to support

#### Scenario: A signed drift value understates uncertainty

- **WHEN** a report computes drift as a signed difference between offset estimates and the result is negative, then adds it to uncertainty
- **THEN** report validation rejects the computation, since a negative signed drift would reduce uncertainty instead of accounting for a backward clock adjustment

#### Scenario: A later sample's own noise is omitted from its drift uncertainty

- **WHEN** `total_uncertainty` is computed using only the initial calibration sample's noise plus the largest raw drift value, without adding each later sample's own calibration-noise uncertainty to its drift estimate
- **THEN** report validation rejects the computation, since the later sample's own measurement noise could partially cancel a real clock change and make the observed drift smaller than the true residual error

#### Scenario: The offset is re-estimated per run instead of shared

- **WHEN** a report computes separate clock-offset estimates for the control and loaded runs in the same matched pair, rather than one shared estimate
- **THEN** report validation rejects the pair, since the delta comparison assumes both runs share one offset so uncertainty cancels out of the delta

### Requirement: Oversized-result workloads measure over-budget materialization cost

The workload matrix SHALL include a `find`/aggregate workload composed of multiple documents whose individual encoded size is well within the cache's configured max-entry size, such that only their aggregate encoded size exceeds it — never a single document that alone exceeds the max-entry size. This distinguishes measuring full-result materialization cost across many documents (relevant to whether incremental abandonment is worth building) from measuring single-document rejection, which any workload with one oversized document would already exercise trivially. The report SHALL record two distinct costs, never conflated or substituted for each other: the end-to-end materialization cost (cursor fetch, transport, and the shipped one-shot encode call together) this workload incurs before the result is discarded as oversized, informational and consistent with how this benchmark reports materialization cost elsewhere; and, separately, the two encoder-invocation-only costs described below that feed the incremental-abandonment savings comparison. Only the latter pair feeds that comparison — the end-to-end figure SHALL NOT be used as a substitute for either encoder-invocation cost, since it includes transport and cursor-fetch time neither incremental abandonment nor the shipped strategy could ever avoid. Because incremental abandonment is not implemented, and the shipped admission path performs one BSON encode of the complete materialized result rather than encoding document-by-document with an observable running total (`implement-cached-read-api`), the benchmark SHALL NOT attempt to instrument or checkpoint that single encode call internally — there is no intermediate state inside it to observe.

The benchmark SHALL determine the crossover prefix empirically, not by summing each document's individually pre-computed encoded size: the final admitted value includes array-wrapper and single-field-envelope overhead beyond the sum of individual document sizes (`implement-cache-core`), so a prefix selected by naive summation could still fall short of the true max-entry limit once actually enveloped and encoded. It SHALL instead invoke the shipped encoder — including its real envelope wrapping, the same unmodified one-shot encoding function used in production, never a separate or incremental implementation — on successive candidate prefixes via a bounded search, to identify the exact prefix length at which the fully-enveloped encoded size first exceeds the max-entry size. This search is setup work, not sampled measurement. The final, timed measurement SHALL invoke the shipped encoder repeatedly on the identified prefix and repeatedly on the complete result — a pre-registered minimum repetition count for each, fixed before sampling — and aggregate each set using a pre-registered rule (e.g. the median), never a single sample of either: scheduling jitter, garbage collection, and allocator behavior can shift a single invocation's timing enough to change which side of the acceptable-savings threshold the comparison falls on, and this decision's evidence quality depends on that comparison being reproducible rather than incidentally noisy.

Because an incremental admission strategy would perform genuinely different work than the shipped one-shot encoder invoked on a smaller input — per-document encode calls, running-size bookkeeping, and early-abandonment logic the one-shot path has none of, potentially using different primitives entirely — the prefix-invocation cost is not a direct measurement of that candidate strategy's actual cost, and it is not a proven bound on it either: a real incremental encoder could in principle use cheaper primitives than the shipped bulk one-shot encoder and cost less than this comparison suggests, just as plausibly as it could cost more from added bookkeeping. Neither direction of this comparison is therefore conclusive proof about the real candidate strategy. The benchmark configuration SHALL fix, before either measurement is taken, an acceptable-savings threshold (a minimum absolute reduction between the full-result and prefix encoder-invocation costs) that this comparison is judged against, never chosen or adjusted after observing results — but this comparison SHALL be treated only as a cheap triage signal for whether building a real incremental prototype is worth the engineering investment, never as the architectural decision itself: (a) if the measured difference does not meet the threshold, that is evidence the one-shot encoding work being skipped is small enough that prototyping is unlikely to be worthwhile, and a report may recommend leaving `implement-cached-read-api`'s admission as shipped without prototyping — but this is a cost-benefit judgment about whether to invest in finding out, not a proof that a real incremental strategy would fail the threshold; (b) if the measured difference meets the threshold, that justifies opening a follow-up change to build a minimal incremental-admission prototype and measure its actual cost, including its own bookkeeping overhead, against the same threshold. Neither branch of a report reaching this requirement SHALL claim to have conclusively decided whether to ship incremental abandonment — that decision always requires a real prototype's measured cost, per (b), or an explicit, separately-justified decision not to pursue it, per (a).

#### Scenario: An over-budget result is measured

- **WHEN** a benchmark report claims to measure the cost of admitting an oversized `find`/aggregate result
- **THEN** setup or report validation rejects it unless the workload's result comprises multiple individually-fitting documents whose aggregate encoded size exceeds the configured max-entry size, and the report records the materialization cost paid before rejection

#### Scenario: The end-to-end cost is substituted for an encoder-invocation cost

- **WHEN** a report uses the workload's end-to-end materialization cost (including cursor fetch and transport) as either operand of the incremental-abandonment savings comparison, rather than the two dedicated encoder-invocation-only costs
- **THEN** report validation rejects the substitution, since the end-to-end figure includes time neither admission strategy could ever avoid

#### Scenario: A single oversized document is mistaken for the required workload

- **WHEN** a workload's oversized result consists of one document whose own encoded size already exceeds the max-entry size
- **THEN** setup or report validation rejects it as the oversized-result workload, since it cannot provide evidence about the cost of materializing many documents before their aggregate crosses the limit

#### Scenario: The oversized-result workload is primed by rejection, not by a hit

- **WHEN** the oversized-result workload completes its warmup
- **THEN** setup verifies a positive delta on the oversized-bypass counter (`stream-cost-observability`) rather than the admission/hit counter deltas required of other cache workload variants

#### Scenario: A savings threshold is chosen after seeing results

- **WHEN** a report sets or adjusts the acceptable-savings threshold between full-result and prefix encoder-invocation cost after observing the oversized-result workload's measurements
- **THEN** report validation rejects the threshold as not pre-registered

#### Scenario: Full-result cost is claimed without a prefix comparison

- **WHEN** a report claims incremental abandonment is or is not warranted using only the full-result encoder-invocation cost, without the prefix encoder-invocation cost measurement
- **THEN** report validation rejects the claim as lacking the comparison the decision is defined against

#### Scenario: Transport cost is included in the savings comparison

- **WHEN** a report computes the full-result-versus-prefix comparison using total materialization cost (including cursor fetch or network transport) rather than the shipped encoder's invocation cost alone
- **THEN** report validation rejects the comparison as overstating incremental abandonment's possible savings, since transport cost is paid by both strategies regardless

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

#### Scenario: A triage signal is treated as conclusive proof either way

- **WHEN** a report concludes incremental abandonment is warranted, or definitively not warranted, directly from the prefix-versus-full-result encoder-invocation comparison, without either a follow-up prototype measurement or an explicit acknowledgment that the negative conclusion is a cost-benefit judgment rather than a proof
- **THEN** report validation rejects the conclusion, since this comparison does not bound a real incremental strategy's cost in either direction — a different encoding approach could cost more or less than this comparison suggests

#### Scenario: A below-threshold result is reported as a judgment, not a proof

- **WHEN** the prefix-versus-full-result encoder-invocation difference does not meet the pre-registered threshold
- **THEN** a report may recommend not prototyping incremental abandonment, but SHALL characterize that recommendation as a cost-benefit judgment about the engineering investment, not as evidence that a real incremental strategy would fail the threshold

### Requirement: Reports preserve per-variant latency distributions

For every raw/cache pair and operation-bearing workload/data-size combination, the benchmark SHALL record operation-latency samples or a distribution for each variant. Cache-variant latency data SHALL be associated with the observed cache outcome, and raw-variant latency data SHALL be associated with the raw variant. Each report row for an operation-bearing variant SHALL preserve enough distribution data to compare variants, including sample count and at least p50, p95, and p99 latency values. An idle variant SHALL instead record zero operations and an explicit no-latency-samples marker for each variant.

#### Scenario: A report has only aggregate timing

- **WHEN** a benchmark report includes total wall time but lacks per-variant latency distributions associated with cache outcomes
- **THEN** report validation rejects the report as insufficient for an operation-bearing workload's cache cost and benefit conclusions

### Requirement: Controlled measurements are not generalized

The suite SHALL report monotonic wall time, benchmark-process CPU, and controlled MongoDB-container CPU for every controlled run. For every operation-bearing variant in a controlled run, it SHALL report the required per-variant latency distribution; an idle variant SHALL report the explicit zero-operation and no-latency-samples marker. If MongoDB-container CPU cannot be collected from the configured cgroup or runtime, setup SHALL fail and the run SHALL not produce a controlled report. Optional byte-proxy mode SHALL count only its direct benchmark path. It SHALL permit compressed or uncompressed traffic on that path and SHALL refuse unsupported TLS, discovery, or shared-connection configurations. The report SHALL identify the requested and verified negotiated compressor, or explicitly identify an uncompressed connection; a compressed run whose negotiated mode cannot be verified SHALL fail setup. CI SHALL retain these reports as workload and architectural cost evidence without using their absolute or cross-host timings as a pass/fail gate. This does not prohibit `performance-regression-guard` from gating a pull request on matched, same-run relative measurements of base and proposed implementations under its separate coverage and noise policy.

#### Scenario: Proxy mode is requested with compression

- **WHEN** a controlled benchmark requests byte-proxy mode with a supported wire compressor on an isolated direct connection
- **THEN** the benchmark counts the bytes crossing that path and identifies the verified negotiated compressor, without presenting those bytes as deployment-wide traffic

#### Scenario: A compressed connection is not established

- **WHEN** a compression comparison requests a compressor that is unavailable or is not negotiated with the server
- **THEN** setup fails rather than recording an uncompressed run under the requested compressor's label

#### Scenario: A workload variant is not primed

- **WHEN** a cache workload variant other than the oversized-result workload completes warmup without positive counter deltas for at least one cache admission and one cache hit for that variant
- **THEN** setup or report validation fails before sampled results are accepted

#### Scenario: Controlled container CPU is unavailable

- **WHEN** a controlled benchmark cannot collect MongoDB-container CPU from its cgroup or runtime
- **THEN** setup fails and the benchmark does not emit a controlled report with an incomplete CPU measurement

#### Scenario: A controlled report is slower than a historical report

- **WHEN** a controlled stream-cost report has a larger absolute timing value than a report from another run or host
- **THEN** CI retains the report without failing on that timing difference alone

### Requirement: Wire compression is compared on matched stream workloads

The benchmark SHALL compare no compression, Snappy, zlib, and Zstandard against the same isolated MongoDB server version, resource limits, document data, operation schedule, and direct client topology. Each mode SHALL have a no-stream control and a cache path with the library's normal database change stream. The matrix SHALL include an idle polling window and active read/write windows with small and large documents, so both the stream's steady cost and its cost during change delivery are visible. Runs SHALL reset application data, cache state, and stream cursor before each sample, warm up before measurement, repeat and counterbalance mode and path order, and record the actual operation and event counts. A failed or unmatched run SHALL invalidate the affected comparison.

#### Scenario: A four-mode report is produced

- **WHEN** the benchmark completes its comparison
- **THEN** every mode has matched no-stream and stream-watching measurements for the registered workloads, sizes, and repetitions, with counts and order recorded

#### Scenario: A mode silently executes fewer writes

- **WHEN** a run executes or observes fewer operations or change events than its matched schedule requires
- **THEN** report validation rejects that run as incomparable

### Requirement: Compression reports expose server, latency, and wire trade-offs

For every matched window, the report SHALL record MongoDB-container CPU time, monotonic elapsed time, and direct-path bytes sent and received, with the proxy's path scope stated. Active windows SHALL report sample count and at least p50, p95, and p99 for applicable read, write, and write-to-invalidation latency; idle windows SHALL explicitly report no operation latency samples. The report SHALL show each mode's stream-minus-control CPU and byte deltas alongside the absolute path values. It SHALL retain the individual repetitions and environment, compressor, workload, and sample metadata needed to reproduce the comparison, and SHALL identify any inconclusive or noisy result rather than converting it into a performance claim.

#### Scenario: A report attributes the stream's cost

- **WHEN** a reader compares one compressor's stream-watching path with its no-stream control
- **THEN** the report shows both paths' CPU and direct-path bytes and their difference, while labeling that difference an approximation of the stream's added cost

#### Scenario: An idle window is reported

- **WHEN** a window contains no sampled reads or writes
- **THEN** its CPU and byte measurements remain available and its operation latency is marked unavailable with zero samples

### Requirement: Compression guidance follows retained measurements

Public performance guidance SHALL link a retained, versioned four-mode report and name one recommended PyMongo client compressor setting for the measured workload, including no compression when warranted. The recommendation SHALL prioritize server CPU cost and write-to-invalidation latency associated with watching the change stream, then consider direct-path byte savings, and SHALL disclose material workload and environment limits. If the measurements do not distinguish the modes reliably, guidance SHALL retain the current no-compression PyMongo default and state that the comparison is inconclusive; it SHALL NOT claim that mode is universally fastest or cheapest. The benchmark SHALL NOT change the public cache API or silently override the caller's client configuration.

#### Scenario: One mode offers a clear trade-off

- **WHEN** repeated measurements support a recommendation under the registered decision rule
- **THEN** the guidance names that mode, links the report, and explains its CPU, latency, and network trade-offs for the library's change-stream workload

#### Scenario: Differences are within measurement noise

- **WHEN** the registered rule cannot distinguish a mode from no compression
- **THEN** guidance keeps no compression as the documented default and labels the result inconclusive rather than claiming a measured win

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

### Requirement: The change-stream resource-cost comparison documents what its values cover

Each path's values cover that path's whole run - its sampled reads and shared writes as well as, for the cache path, the change stream itself - so the report SHALL document that the difference between the two paths, not either value alone, approximates the change stream's added cost. This comparison is retained evidence, not a pass/fail gate, consistent with this capability's existing treatment of CPU and timing measurements.

#### Scenario: A report explains what the comparison values cover

- **WHEN** a controlled report includes the change-stream resource-cost comparison
- **THEN** the report documents that each path's value covers that path's whole run, and that the difference between the two paths - not either value alone - approximates the change stream's added cost
