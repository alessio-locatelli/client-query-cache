## MODIFIED Requirements

### Requirement: Snapshots expose scoped cache and stream measurements

With telemetry enabled, manager snapshots SHALL expose immutable cache and stream-cost measurements with explicit scope.

#### Scenario: An application exports measurements

- **GIVEN** telemetry is enabled
- **WHEN** an application serializes a manager measurement snapshot
- **THEN** the output states each measurement scope and contains no cached document or credential value

### Requirement: Snapshots measure invalidation delivery lag

With telemetry enabled, the manager SHALL measure event wall-time to applied-invalidation lag per database stream.

#### Scenario: Heavy unrelated write traffic delays invalidation

- **GIVEN** telemetry is enabled
- **WHEN** a database-scoped stream is processing a high volume of writes to collections it is not caching
- **THEN** the exposed invalidation-lag distribution for that stream reflects any resulting delay in delivering invalidations to the cached collections sharing it

#### Scenario: Lag is computed from a comparable clock

- **GIVEN** telemetry is enabled
- **WHEN** the manager computes invalidation delivery lag for a routed event
- **THEN** it subtracts the event's projected `wallTime` from the local time it applied the invalidation, never the event's `clusterTime`, and the snapshot labels the result with its clock-skew limitation

### Requirement: Lag samples are retained in bounded contiguous windows

With telemetry enabled, the manager SHALL retain bounded, gap-free event-count windows of applied-invalidation lag samples.

#### Scenario: Lag telemetry does not grow without bound

- **GIVEN** telemetry is enabled
- **WHEN** a database-scoped stream processes a sustained high volume of events over a long-lived run
- **THEN** the retained invalidation-lag distribution stays within its configured bounded size instead of retaining one sample per event indefinitely

#### Scenario: A capture window is defined by duration instead of a fixed event count

- **GIVEN** telemetry is enabled
- **WHEN** a capture window is bounded by wall-clock duration rather than a fixed, pre-registered number of contiguous filtered events
- **THEN** the configuration is rejected, since a duration-bounded window has an unbounded, workload-dependent event count and cannot support uniform block-bootstrap selection or a fixed memory bound

#### Scenario: An uncached-collection event is treated as part of window contents

- **GIVEN** telemetry is enabled
- **WHEN** an event the router inspects and discards for an uncached collection is counted toward a capture window's event total or its separation from adjacent windows
- **THEN** the configuration is rejected, since that event has no invalidation timestamp and is not part of this distribution; windows are defined over the filtered sequence of invalidation-producing events only

#### Scenario: A histogram is used instead of captured windows

- **GIVEN** telemetry is enabled
- **WHEN** the manager retains this distribution in a fixed-bucket histogram rather than complete captures of pre-registered windows
- **THEN** the configuration is rejected, since a histogram cannot support the block-bootstrap confidence-interval computation this distribution's percentile comparisons require

#### Scenario: Captured events have internal gaps

- **GIVEN** telemetry is enabled
- **WHEN** a capture window's retained events are missing events from the filtered invalidation-event sequence that actually fell within that window's span
- **THEN** the configuration is rejected, since a window with internal gaps is not a genuinely contiguous block and cannot serve as a valid block-bootstrap block
