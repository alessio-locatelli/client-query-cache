# stream-cost-observability Specification

## Purpose

This capability exposes safe, precisely labelled cache and stream measurements that can inform workload-specific benchmark analysis without exposing application data.

## Requirements

### Requirement: Snapshots expose scoped cache and stream measurements

Manager snapshots SHALL expose immutable cache and stream-cost measurements with explicit scope.

#### Scenario: An application exports measurements

- **WHEN** an application serializes a manager measurement snapshot
- **THEN** the output states each measurement scope and contains no cached document or credential value

### Requirement: Oversized bypasses have a distinct count

Snapshots SHALL distinguish oversized-result bypasses from other cache bypasses.

#### Scenario: An oversized result is distinguishable from other bypasses

- **WHEN** the manager rejects a result because its encoded size exceeds the configured max-entry size
- **THEN** the oversized-bypass counter increments and no other bypass-reason counter does

### Requirement: Snapshots measure invalidation delivery lag

The manager SHALL measure event wall-time to applied-invalidation lag per database stream.

#### Scenario: Heavy unrelated write traffic delays invalidation

- **WHEN** a database-scoped stream is processing a high volume of writes to collections it is not caching
- **THEN** the exposed invalidation-lag distribution for that stream reflects any resulting delay in delivering invalidations to the cached collections sharing it

#### Scenario: Lag is computed from a comparable clock

- **WHEN** the manager computes invalidation delivery lag for a routed event
- **THEN** it subtracts the event's projected `wallTime` from the local time it applied the invalidation, never the event's `clusterTime`, and the snapshot labels the result with its clock-skew limitation

### Requirement: Raw lag states its clock and topology limits

Raw invalidation lag SHALL be labeled with its clock-offset limitation and supported topology.

#### Scenario: The lag measurement is applied to a sharded topology

- **WHEN** a report applies this invalidation-lag measurement or its single-server calibration to a sharded-cluster benchmark topology
- **THEN** report validation rejects it, since events from different shards originate from different clocks that one offset cannot represent

#### Scenario: A calibrated value is presented under the raw label

- **WHEN** a report presents a clock-offset-corrected lag value under the manager's raw "unmeasured offset" limitation label, instead of a separate field labelled with the calibration's residual uncertainty
- **THEN** report validation rejects the presentation as conflating an uncorrected measurement with a corrected one

#### Scenario: A negative raw sample is clamped or discarded

- **WHEN** the server's clock reads ahead of the benchmark host and a routed event's raw `A − W` value is negative
- **THEN** the bounded structure retains that negative value rather than clamping it to zero or discarding it

### Requirement: Lag samples are retained in bounded contiguous windows

The manager SHALL retain bounded, gap-free event-count windows of applied-invalidation lag samples.

#### Scenario: Lag telemetry does not grow without bound

- **WHEN** a database-scoped stream processes a sustained high volume of events over a long-lived run
- **THEN** the retained invalidation-lag distribution stays within its configured bounded size instead of retaining one sample per event indefinitely

#### Scenario: A capture window is defined by duration instead of a fixed event count

- **WHEN** a capture window is bounded by wall-clock duration rather than a fixed, pre-registered number of contiguous filtered events
- **THEN** the configuration is rejected, since a duration-bounded window has an unbounded, workload-dependent event count and cannot support uniform block-bootstrap selection or a fixed memory bound

#### Scenario: An uncached-collection event is treated as part of window contents

- **WHEN** an event the router inspects and discards for an uncached collection is counted toward a capture window's event total or its separation from adjacent windows
- **THEN** the configuration is rejected, since that event has no invalidation timestamp and is not part of this distribution; windows are defined over the filtered sequence of invalidation-producing events only

#### Scenario: A histogram is used instead of captured windows

- **WHEN** the manager retains this distribution in a fixed-bucket histogram rather than complete captures of pre-registered windows
- **THEN** the configuration is rejected, since a histogram cannot support the block-bootstrap confidence-interval computation this distribution's percentile comparisons require

#### Scenario: Captured events have internal gaps

- **WHEN** a capture window's retained events are missing events from the filtered invalidation-event sequence that actually fell within that window's span
- **THEN** the configuration is rejected, since a window with internal gaps is not a genuinely contiguous block and cannot serve as a valid block-bootstrap block

### Requirement: Lag-window numeric fields require built-in integers

Lag-window count, events per window, and event separation SHALL accept only exact built-in integers. Boolean values, integer subclasses, floats including NaN and infinities, strings, null values, and other types SHALL raise the public configuration error at configuration construction before telemetry allocation.

#### Scenario: Invalid runtime lag-window input

- **WHEN** any numeric lag-window field receives a non-built-in-integer value
- **THEN** construction raises `CacheConfigurationError` naming that field rather than failing later or retaining unbounded samples

### Requirement: Lag-window numeric ranges remain enforceable

Lag-window count and events per window SHALL be positive; event separation SHALL be nonnegative. Invalid values SHALL raise the public configuration error at configuration construction. Public configuration guidance SHALL state these constraints.

#### Scenario: Zero separation is valid

- **WHEN** count and events per window are positive built-in integers and separation is zero
- **THEN** construction succeeds with adjacent windows permitted

#### Scenario: A lag-window range is invalid

- **WHEN** count or events per window is zero or negative, or event separation is negative
- **THEN** construction raises `CacheConfigurationError` identifying the violated constraint

### Requirement: Lag capture plans are registered before sampling

The capture plan SHALL fix window count, event count, and separation before a benchmark run.

#### Scenario: The capture plan cannot resolve the compared percentile

- **WHEN** the total event count captured across the configured windows is below the minimum sample count the configured percentile requires, or below what its confidence-interval computation requires at the pre-registered confidence level
- **THEN** the manager's capture-plan configuration is rejected as insufficient for the percentile it is required to support

#### Scenario: A capture plan is chosen after seeing results

- **WHEN** a report's window count, fixed events per window, or window separation is not part of the pre-run configuration fixed before sampling
- **THEN** report validation rejects the confidence interval as not pre-registered

#### Scenario: A report claims the capture plan handles arbitrary dependence

- **WHEN** a report presents the pre-registered window size, count, and separation as proven sufficient for any event-dependence pattern
- **THEN** it is rejected unless it discloses that the plan reflects the best available burst-duration assumption for the measured workload and cannot prove sufficiency for arbitrary dependence

### Requirement: Lag windows support uniform block resampling

Benchmark confidence intervals SHALL resample complete equal-sized capture windows uniformly.

#### Scenario: An order-statistic interval is used instead of a block bootstrap

- **WHEN** a report computes a percentile confidence interval using the plain order-statistic method, treating the retained lag samples as independent
- **THEN** report validation rejects the interval, since dependence between consecutive routed events (bursty or queued writes) can take forms — nonlinear, phase-locked — that this method assumes away

#### Scenario: Windows are resampled by weighted size instead of uniformly

- **WHEN** a block bootstrap draws capture windows with probability weighted by their event count, rather than uniformly among the equal-sized windows
- **THEN** the resampling is rejected, since equal-sized windows require uniform selection — size-weighted selection of a block whose full content is also included double-counts large blocks quadratically

### Requirement: Stream projection preserves coherency fields

Benchmark instrumentation SHALL observe the same projected event fields required for invalidation and resume. It SHALL not request full-document update lookup solely for invalidation measurement.

#### Scenario: A projected update is processed

- **WHEN** the manager receives an update event during a measured run
- **THEN** it can route invalidation and preserve its resume token without a full document payload

### Requirement: Stream-poll counts describe worker calls

The existing `stream_polls` counter SHALL be labelled as the number of manager calls into change-stream iteration, not the number of MongoDB `getMore` commands. Documentation and benchmark reports SHALL NOT use it as a wire-command count. An await-time comparison SHALL obtain actual `getMore` counts from command-level observation and keep them separately labelled from the manager counter.

#### Scenario: One iteration call issues multiple commands

- **WHEN** the manager makes one change-stream iteration call and the driver issues multiple `getMore` commands before returning an event
- **THEN** `stream_polls` records the one manager call while command-level observation records each `getMore`
