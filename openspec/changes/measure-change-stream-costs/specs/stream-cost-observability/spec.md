## Purpose

Expose the cache benefit and change-stream activity needed to judge a workload
without misrepresenting application-level measurements as wire-level costs.

## ADDED Requirements

### Requirement: Inspectable cache-benefit counters
The cache manager SHALL expose monotonically increasing counters for document
and derived-result hits, misses, unhealthy-state bypasses, cache admissions,
admission rejections, evictions, invalidations, and MongoDB reads avoided by
cache hits. It SHALL expose an estimated BSON payload-byte total for values
returned from cache and label that total as an estimate rather than wire bytes.

#### Scenario: Cache hit contributes to benefit metrics
- **WHEN** an eligible read returns a value from the cache
- **THEN** inspection reports one avoided MongoDB read and increases only the
  explicitly estimated BSON payload-byte total for that result

#### Scenario: Recovering manager bypasses cache
- **WHEN** a manager is recovering from a stream interruption
- **THEN** an eligible read increments the bypass counter and does not increment
  the avoided-read or estimated-payload totals

### Requirement: Inspectable stream-activity counters
The cache manager SHALL expose the count of observed change events, the BSON
size of each event after the configured invalidation projection, events that
did not evict a resident document, stream poll attempts, empty poll results,
and elapsed time spent waiting for stream polls. It SHALL identify these values
as client-observed logical activity.

#### Scenario: Idle stream polling
- **WHEN** a healthy stream poll returns no event
- **THEN** inspection increases the empty-poll count and observed wait duration
  without recording an event payload

#### Scenario: Uncached document event
- **WHEN** the stream receives an event whose document key has no resident
  document entry
- **THEN** inspection records the event and the no-resident-document outcome
  while still applying derived-result invalidation

### Requirement: Measurement scope and privacy
Runtime inspection SHALL state that its byte counters exclude MongoDB wire
protocol envelopes, transport encryption, compression, TCP retransmission, and
server-side CPU. It SHALL NOT retain or expose document values, query values,
connection strings, credentials, or resume-token contents as metrics labels.

#### Scenario: Application exports a snapshot
- **WHEN** an application reads or exports a manager measurement snapshot
- **THEN** the snapshot contains counters and configured measurement scope but
  no cached document value, query value, credential, or resume token
