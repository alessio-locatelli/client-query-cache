## ADDED Requirements

### Requirement: Mixed concurrency tests cover both execution models

Integration tests SHALL exercise one process-local manager with concurrent synchronous readers or asynchronous reader tasks while an independent client performs inserts, updates, replacements, and deletes across hot and cold collections.

#### Scenario: Mixed CRUD runs against cached readers

- **WHEN** either execution model runs the workload against disposable MongoDB
- **THEN** all four readers remain running and each completes at least ten reads during every ten-write CRUD phase, without a reader catch-up barrier, both collections are exercised, and worker exceptions fail the test

### Requirement: Concurrent reads respect processed invalidations

Mixed concurrency tests SHALL reject values older than invalidations processed before a read begins and verify exact values at quiescent checkpoints, including absence and insertion after a cached negative result.

#### Scenario: An external write is processed

- **WHEN** the manager processes a document's change event
- **THEN** subsequent reads cannot return an older version, and checkpoint reads match the written document or its deletion

#### Scenario: A deleted document is cached as absent

- **WHEN** checkpoint reads after a processed deletion return `None`
- **THEN** repeated identity and namespace reads issue no MongoDB reads, and the next insertion invalidates those cached negative results

### Requirement: Reads spanning invalidation cannot populate the cache

Concurrency tests SHALL force a database read to span a processed invalidation and verify that its earlier result is not admitted, while allowing that in-flight read to return its earlier database result.

#### Scenario: A write occurs after the database returns a document

- **WHEN** a paused identity or namespace read resumes after its invalidation is processed
- **THEN** its earlier result can be returned to its caller, but a subsequent read misses and obtains the new value

### Requirement: Recovery fails closed during concurrent reads

Concurrency tests SHALL force lost-history recovery during active reads and verify that lookup and admission remain disabled throughout uncertainty and that reads spanning recovery cannot populate the cache after health is restored.

#### Scenario: Resume history is lost

- **WHEN** recovery is held open while cached readers remain active
- **THEN** reads reach MongoDB without adding hits or admissions, and a paused pre-recovery result is rejected after recovery

### Requirement: Stress runs are bounded and reproducible

Mixed concurrency tests SHALL have documented operation counts, configurable cycle counts, a deterministic operation schedule, and a hard timeout that fails stalled work. Default cases SHALL run in the normal integration tier without quantitative throughput thresholds.

#### Scenario: A contributor repeats or extends a run

- **WHEN** a contributor repeats the documented command or increases the cycle count
- **THEN** the operation schedule can be reproduced or extended, and stalled workers still fail within the configured timeout
