## Purpose

This capability exposes safe, precisely labelled cache and stream measurements that can inform workload-specific benchmark analysis without exposing application data.

## ADDED Requirements

### Requirement: Measurement snapshots have explicit scope

The manager SHALL expose immutable counts for cache outcomes, stream polls, logical projected-event bytes, invalidations, and resident cache bytes. Cache-outcome counts SHALL distinguish a bypass caused by an oversized result (encoded size exceeding the configured max-entry size) from every other bypass or rejection reason, as its own labelled counter, so a benchmark can verify a workload was rejected specifically for being oversized rather than for an unrelated reason. It SHALL label logical payload measures as distinct from network wire bytes and server CPU, and SHALL omit queries, documents, credentials, and resume tokens.

#### Scenario: An application exports measurements

- **WHEN** an application serializes a manager measurement snapshot
- **THEN** the output states each measurement scope and contains no cached document or credential value

#### Scenario: An oversized result is distinguishable from other bypasses

- **WHEN** the manager rejects a result because its encoded size exceeds the configured max-entry size
- **THEN** the oversized-bypass counter increments and no other bypass-reason counter does

### Requirement: Measurement snapshots include invalidation delivery lag

The manager SHALL expose an immutable distribution of invalidation delivery lag — the elapsed time between a routed change event's projected server `wallTime` and the moment the manager applies that event's invalidation — scoped per active database-scoped stream, so a stream falling behind on one database's traffic is distinguishable from another's. This measurement is valid only against the replica-set benchmark topology already decided for this change (`stream-cost-benchmarking`'s Decisions): on a sharded cluster, a database-scoped stream can aggregate events originating from multiple shard `mongod`s, each with its own clock, and `wallTime` values from different sources cannot be compared against one single-server offset — a report SHALL NOT apply this lag measurement or its calibration to a sharded topology unless a future change adds per-source event attribution and per-source calibration. It SHALL NOT use `clusterTime` for this measurement: `clusterTime` is a logical BSON timestamp, not an elapsed-time-comparable clock value, and subtracting it from a local wall-clock reading would produce a meaningless duration. Because this lag compares the MongoDB server's clock against the benchmark host's clock, the manager's raw exposed distribution SHALL carry an explicit clock-skew limitation label stating that its values include unmeasured server-to-host clock offset and are not a substitute for a same-clock, single-host latency measurement. This raw label describes the manager's own uncorrected exposure only: a report that applies `stream-cost-benchmarking`'s calibration to produce a clock-offset-corrected distribution SHALL present that corrected distribution as a separate, distinctly labelled field — carrying its own residual-uncertainty label (the calibration's `total_uncertainty`) — never reusing or presenting it under the raw "unmeasured offset" label, since the offset is no longer unmeasured once calibration has been applied to it. A report SHALL NOT conflate the two fields, the same way `stream-cost-benchmarking`'s byte-proxy and container-CPU measurements keep their own labelled limitations distinct from unlabelled values. This distribution SHALL be retained in a bounded structure scoped to a pre-registered capture plan (see below) rather than one sample per routed event without limit for the manager's entire lifetime, so a long-lived manager on a high-volume database cannot grow this telemetry's memory unboundedly outside the cache's own budget; a benchmark run SHALL reset or scope this structure per run so one run's distribution never mixes with another's. A fixed-bucket histogram SHALL NOT be used for this distribution: `stream-cost-benchmarking`'s confidence-interval computation needs the retained raw values (not bucket counts), and it needs them as contiguous, gap-free captures rather than individually selected samples (see below) — a histogram's bucket counts preserve neither. The raw, pre-calibration value of `A − W` is routinely negative whenever the server's clock reads ahead of the benchmark host's — this is expected, ordinary behavior, not an error condition — so the bounded structure SHALL store and support signed values without clamping negative raw samples to zero, discarding them, or otherwise biasing the distribution; a structure that cannot represent a negative raw sample would corrupt the very correction `stream-cost-benchmarking`'s calibration is meant to apply. Because a single serial router processes events in one ordered sequence, consecutive lag observations can be dependent in ways a single summary statistic cannot rule out — not only simple lag-1 correlation, but nonlinear dependence and phase-locked bursts. A block bootstrap is the general-purpose method that remains valid under such dependence without needing it characterized in advance, but it requires its blocks to be genuinely contiguous slices of the original event sequence; ordinary reservoir sampling under a bounded capacity discards most events on a high-volume stream, so retained samples — even kept in arrival order — are not temporally adjacent to each other and cannot serve as the block bootstrap's blocks. The manager SHALL therefore retain this distribution not as a reservoir sample of individually selected events, but as complete, contiguous captures defined over the filtered sequence of events that actually produce a lag sample — i.e. events resulting in an applied invalidation — skipping over, and never counting toward window contents or separation, any event the router inspects and discards for an uncached collection, which has no invalidation timestamp and is not part of this distribution at all. Each capture window SHALL capture a fixed, pre-registered number of contiguous events from that filtered sequence (not a fixed time duration), so every window is the same size by construction; a pre-registered minimum separation (by filtered event count or elapsed wall-clock time) SHALL apply between the end of one window and the start of the next. Because windows are equal-sized by construction, the total memory bound is simply (window count × fixed events per window), fixed before the run executes with no dependence on the observed event rate — the overflow/capacity concern that a variable-duration window would raise does not arise here, since a window closes once it has captured its fixed event count, whatever real time that took. The number of windows and the fixed events per window SHALL be chosen so the total retained event count meets `stream-cost-benchmarking`'s sample-count floor and its confidence-interval requirements. `stream-cost-benchmarking`'s block bootstrap SHALL resample among these equal-sized windows uniformly (each window equally likely to be drawn) — never weighted by window size, which is now moot since all windows are the same size, and never weighted by any other criterion, since uniform selection among equal-size blocks is the standard, correctly-calibrated moving-block-bootstrap construction; weighting selection probability by size while also including a block's full content, as an earlier draft of this requirement did, would double-count large blocks quadratically rather than represent them proportionally. The number of capture windows, their fixed event count, and their separation are pre-registered choices reflecting the best available domain understanding of typical burst duration for this workload, not a value proven sufficient for arbitrary dependence structure — a report SHALL disclose this as an assumption, the same way other unprovable assumptions in this benchmark are disclosed.

#### Scenario: Heavy unrelated write traffic delays invalidation

- **WHEN** a database-scoped stream is processing a high volume of writes to collections it is not caching
- **THEN** the exposed invalidation-lag distribution for that stream reflects any resulting delay in delivering invalidations to the cached collections sharing it

#### Scenario: The lag measurement is applied to a sharded topology

- **WHEN** a report applies this invalidation-lag measurement or its single-server calibration to a sharded-cluster benchmark topology
- **THEN** report validation rejects it, since events from different shards originate from different clocks that one offset cannot represent

#### Scenario: Lag is computed from a comparable clock

- **WHEN** the manager computes invalidation delivery lag for a routed event
- **THEN** it subtracts the event's projected `wallTime` from the local time it applied the invalidation, never the event's `clusterTime`, and the snapshot labels the result with its clock-skew limitation

#### Scenario: A calibrated value is presented under the raw label

- **WHEN** a report presents a clock-offset-corrected lag value under the manager's raw "unmeasured offset" limitation label, instead of a separate field labelled with the calibration's residual uncertainty
- **THEN** report validation rejects the presentation as conflating an uncorrected measurement with a corrected one

#### Scenario: Lag telemetry does not grow without bound

- **WHEN** a database-scoped stream processes a sustained high volume of events over a long-lived run
- **THEN** the retained invalidation-lag distribution stays within its configured bounded size instead of retaining one sample per event indefinitely

#### Scenario: A capture window is defined by duration instead of a fixed event count

- **WHEN** a capture window is bounded by wall-clock duration rather than a fixed, pre-registered number of contiguous filtered events
- **THEN** the configuration is rejected, since a duration-bounded window has an unbounded, workload-dependent event count and cannot support uniform block-bootstrap selection or a fixed memory bound

#### Scenario: An uncached-collection event is treated as part of window contents

- **WHEN** an event the router inspects and discards for an uncached collection is counted toward a capture window's event total or its separation from adjacent windows
- **THEN** the configuration is rejected, since that event has no invalidation timestamp and is not part of this distribution; windows are defined over the filtered sequence of invalidation-producing events only

#### Scenario: A negative raw sample is clamped or discarded

- **WHEN** the server's clock reads ahead of the benchmark host and a routed event's raw `A − W` value is negative
- **THEN** the bounded structure retains that negative value rather than clamping it to zero or discarding it

#### Scenario: The capture plan cannot resolve the compared percentile

- **WHEN** the total event count captured across the configured windows is below the minimum sample count the configured percentile requires, or below what its confidence-interval computation requires at the pre-registered confidence level
- **THEN** the manager's capture-plan configuration is rejected as insufficient for the percentile it is required to support

#### Scenario: A histogram is used instead of captured windows

- **WHEN** the manager retains this distribution in a fixed-bucket histogram rather than complete captures of pre-registered windows
- **THEN** the configuration is rejected, since a histogram cannot support the block-bootstrap confidence-interval computation this distribution's percentile comparisons require

#### Scenario: An order-statistic interval is used instead of a block bootstrap

- **WHEN** a report computes a percentile confidence interval using the plain order-statistic method, treating the retained lag samples as independent
- **THEN** report validation rejects the interval, since dependence between consecutive routed events (bursty or queued writes) can take forms — nonlinear, phase-locked — that this method assumes away

#### Scenario: Captured events have internal gaps

- **WHEN** a capture window's retained events are missing events from the filtered invalidation-event sequence that actually fell within that window's span
- **THEN** the configuration is rejected, since a window with internal gaps is not a genuinely contiguous block and cannot serve as a valid block-bootstrap block

#### Scenario: A capture plan is chosen after seeing results

- **WHEN** a report's window count, fixed events per window, or window separation is not part of the pre-run configuration fixed before sampling
- **THEN** report validation rejects the confidence interval as not pre-registered

#### Scenario: Windows are resampled by weighted size instead of uniformly

- **WHEN** a block bootstrap draws capture windows with probability weighted by their event count, rather than uniformly among the equal-sized windows
- **THEN** the resampling is rejected, since equal-sized windows require uniform selection — size-weighted selection of a block whose full content is also included double-counts large blocks quadratically

### Requirement: Stream projection preserves coherency fields

Benchmark instrumentation SHALL observe the same projected event fields required for invalidation and resume. It SHALL not request full-document update lookup solely for invalidation measurement.

#### Scenario: A projected update is processed

- **WHEN** the manager receives an update event during a measured run
- **THEN** it can route invalidation and preserve its resume token without a full document payload
