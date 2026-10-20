# Spec Delta

## ADDED Requirements

### Requirement: Multi-process fault recovery has real regression coverage

Fault-recovery regression tests SHALL use separate worker processes and real
MongoDB instances. They SHALL assert correct observable reads and cache state,
and SHALL NOT present test deadlines as measured recovery times.

#### Scenario: Workers recover after primary stepdown

- **WHEN** MongoDB steps down its current primary and elects another member
- **THEN** direct and independently cached workers read the latest written
  revision through the elected primary
- **AND** direct workers do not open change streams

#### Scenario: Workers recover after TCP connection loss

- **WHEN** the harness severs worker TCP connections and a document is updated
- **THEN** direct and independently cached workers read the latest revision
- **AND** independent workers reopen their change streams and process the
  update invalidation
- **AND** direct workers do not open change streams

#### Scenario: A history-lost error clears an independent worker's cache

- **WHEN** an independent worker receives the MongoDB history-lost error while
  reopening its change stream
- **THEN** its cache is cleared, its stream reopens, and its next read returns
  the current document revision
- **AND** the test does not require a direct worker for this stream-specific
  fault

#### Scenario: A replacement worker serves current data

- **WHEN** the harness kills a worker process and starts a replacement
- **THEN** the replacement becomes ready and reads the current revision from
  MongoDB on the direct and independent-cache paths

### Requirement: Quantitative fault-recovery claims require completed evidence

The regression suite SHALL NOT report quantitative recovery durations,
benchmark performance effects or operational recovery guidance. A quantitative
study requires a separate frozen registration, a validated observer method and
completed fault-matrix evidence.

#### Scenario: The V8 observer gate is inconclusive

- **WHEN** the observer-overhead retry fails its preregistered acceptance gate
- **THEN** the study remains inconclusive, the full matrix does not run, and V8's
  outcome and stop rule remain recorded in the research outcome note
