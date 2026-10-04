# test-environment Specification

## Purpose

This capability provides isolated test tiers that verify MongoDB behavior without requiring a contributor-owned database or container runtime for unit tests.

## Requirements

### Requirement: Tests have explicit execution tiers

The repository SHALL label unit, integration, end-to-end, and benchmark tests. Unit tests SHALL not require a container runtime. Integration tests SHALL use a disposable MongoDB replica set. End-to-end tests SHALL install the built package in a clean environment and exercise the public API with an independent raw writer.

#### Scenario: A contributor runs unit tests without MongoDB

- **WHEN** a contributor runs the documented unit command on a machine without Docker, Podman, or MongoDB
- **THEN** only non-database tests run and the command does not attempt a database connection

### Requirement: Pytest excludes Git-submodule contents

Every pytest invocation provided by the repository, including unit, integration, end-to-end,
coverage, and every tox test tier, SHALL exclude the working-tree contents below the registered
`specifications` Git submodule. The exclusion SHALL apply even when test discovery begins at the
repository root and SHALL not omit repository-owned tests.

#### Scenario: A provided test tier encounters a submodule test

- **WHEN** a contributor runs any documented pytest-based test tier with a Git submodule present
- **THEN** pytest does not collect or execute tests below that submodule and continues to collect the
  tier's repository-owned tests

### Requirement: Database-backed tests own their topology

Database-backed tests SHALL initialize and wait for a disposable single-node MongoDB replica set with dynamically allocated endpoints. They SHALL not use a fixed Compose port, a shared external database, or pre-existing collection state.

#### Scenario: An integration suite starts

- **WHEN** an integration suite runs with an accessible supported container runtime
- **THEN** it creates the replica set, waits for a writable primary, and cleans it up after the suite

### Requirement: Production branch coverage cannot regress

The repository SHALL measure branches for every importable production module and SHALL rely on the configured covdefaults policy rather than an individual command invocation to enforce its coverage threshold. The coverage command SHALL execute the current test suite once under coverage and fail when the report falls below that enforced threshold. The repository SHALL NOT exclude ordinary production paths from measurement.

#### Scenario: A reachable branch is not covered

- **WHEN** a coverage run leaves a production branch unexecuted
- **THEN** the report identifies the missing branch and the command fails if coverage falls below the configured threshold

#### Scenario: A contributor runs the coverage command

- **WHEN** a contributor runs the documented coverage command with an accessible container runtime
- **THEN** unit, integration, and end-to-end tests execute in one pytest invocation and the coverage report is produced from that run

#### Scenario: Planned behavior remains unimplemented

- **WHEN** the baseline includes a production branch owned by `implement-change-stream-coherency`
- **THEN** the branch remains visible as missing coverage without a coverage exclusion

### Requirement: Memory profiling has an explicit execution tier

The repository SHALL provide an opt-in memory test command isolated from ordinary unit, integration, end-to-end, coverage, and latency benchmark runs. The command SHALL profile only memory tests without requiring MongoDB. Missing profiling support, disabled instrumentation, or zero selected memory tests SHALL fail visibly.

#### Scenario: A contributor runs ordinary validation

- **WHEN** a contributor runs a provided correctness, coverage, or latency benchmark command
- **THEN** memory tests are excluded and allocation profiling is not enabled

#### Scenario: A contributor runs memory validation

- **WHEN** a contributor runs the dedicated memory command on the supported Linux toolchain
- **THEN** only the memory tier is profiled, without a database or container runtime

#### Scenario: Memory instrumentation is unavailable

- **WHEN** memory tests are explicitly selected without active allocation instrumentation or the command selects no tests
- **THEN** the command fails visibly rather than reporting an unmeasured success

### Requirement: Memory regression workload exercises bounded cache reclamation

Memory tests SHALL exercise repeated admissions, hits, eviction, invalidation, and namespace clearing at fixed namespace cardinality with a shared 4 MiB BSON budget. Identity entries with aliases and namespace-guarded entries SHALL be covered. Tests SHALL fail on declined expected admissions, absent expected hits or eviction, budget overflow, retained reclaimed metadata, or nonzero entry usage after clearing and closing.

#### Scenario: Workload exceeds cache capacity repeatedly

- **WHEN** each admission mode processes eight cycles of 1,024 fresh documents with 64 KiB payloads across two fixed namespaces, including writes and readmission
- **THEN** admissions and hits succeed, evictions occur, BSON usage stays within budget, and entry indexes, identities, and aliases reference only resident entries at quiescent checkpoints

#### Scenario: Namespace contents are reclaimed

- **WHEN** each workload cycle clears both namespaces with no in-flight admissions
- **THEN** entry count and BSON usage are zero and both namespaces have no entry-index tokens, identity records, or aliases

#### Scenario: The core closes after workload completion

- **WHEN** the workload's core is closed
- **THEN** entry count and BSON usage are zero

### Requirement: Memory ceilings are measured and regression-sensitive

Each memory case SHALL enforce a committed peak-allocation ceiling, calibrated from repeated fresh-process measurements on the CI toolchain. Its ceiling SHALL be the whole-MiB rounding of 1.5 times the largest of ten baseline peaks and SHALL not exceed 32 MiB. Exceeding it SHALL fail. Calibration SHALL demonstrate that retaining all admitted encoded values fails the memory ceiling independently of structural assertions.

#### Scenario: Healthy workload establishes a ceiling

- **WHEN** ten independent baseline runs complete for each case
- **THEN** the documented ceiling follows the calibration rule, is at most 32 MiB, and all baseline runs pass it

#### Scenario: Encoded values accumulate outside budget accounting

- **WHEN** a temporary fault retains every admitted encoded value while normal eviction and reclamation accounting continue
- **THEN** the profiled workload fails its peak-allocation ceiling

#### Scenario: Baseline requires an excessive ceiling

- **WHEN** calibration would require a ceiling above 32 MiB
- **THEN** implementation stops for investigation rather than silently widening the guard

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

### Requirement: Ordinary tests default to bounded parallel execution

Ordinary pytest runs SHALL select workers automatically with at most four workers by default. An explicit numeric worker count SHALL select that count without a repository-imposed ceiling. Contributors SHALL be able to disable parallel execution.

#### Scenario: A host exposes many processors

- **WHEN** an ordinary test run starts on a host exposing more than four usable processors
- **THEN** no more than four test workers start by default

#### Scenario: A contributor adjusts resource use

- **WHEN** a contributor requests two workers or disables parallel execution
- **THEN** tests execute with two workers or in the main process, respectively

#### Scenario: A contributor chooses more workers

- **WHEN** a contributor explicitly requests eight workers
- **THEN** the runner uses eight workers without requiring a second option to raise a maximum

### Requirement: Default scheduling preserves test-file ownership

Parallel runs SHALL keep every test in a file on the same worker by default. This grouping SHALL preserve reuse of file-scoped fixtures without requiring tests to depend on execution order.

#### Scenario: A file shares a disposable replica set and proxy

- **WHEN** a parallel run executes parametrized tests using file-scoped replica-set and proxy fixtures
- **THEN** all tests in that file execute on one worker and reuse those fixtures

### Requirement: Parallel logs do not share writable files

Controller and worker logging SHALL use distinct files when file logging is enabled. Serial logging SHALL retain its configured destination, including disabled file output. Explicit file destinations in parallel mode SHALL remain distinguishable by worker.

#### Scenario: Multiple workers emit diagnostics

- **WHEN** a parallel test run emits controller and worker logs
- **THEN** each process writes its own file without truncating another process's diagnostics

#### Scenario: A contributor chooses a log destination

- **WHEN** a contributor provides a custom log path for a parallel run
- **THEN** worker files use that destination with distinct worker suffixes

#### Scenario: Serial profiling disables file output

- **WHEN** the serial memory command disables file logging
- **THEN** it creates no worker log files

### Requirement: Serial commands support measurement and debugging

Dedicated memory-profiling and benchmark test commands SHALL execute serially. Contributor documentation SHALL identify serial execution for interactive debugging, live captured-output troubleshooting, and isolated benchmark timing.

#### Scenario: A contributor runs dedicated measurement tiers

- **WHEN** the dedicated memory command or benchmark tox environment runs
- **THEN** it starts no distributed workers

#### Scenario: A contributor debugs a failing test

- **WHEN** the contributor follows the documented serial debugging command
- **THEN** the selected test runs in the main process with interactive debugging available

### Requirement: Parallel execution preserves full-suite selection

Enabling parallelism SHALL preserve the full suite's selected tests and existing conditional skips. It SHALL not exclude tests to obtain a speedup. The ordinary full suite SHALL continue excluding the opt-in memory tier.

#### Scenario: Serial and parallel runs use the same inputs

- **WHEN** the full suite runs serially and in parallel with identical selection and environment
- **THEN** both runs collect the same test node IDs and apply the same conditional skip policy

### Requirement: Coverage includes every test worker

The coverage command SHALL aggregate branch measurements from every worker in its single full-suite invocation. Serial and parallel runs with the same inputs SHALL retain the existing production-module scope, threshold, and strict exclusion policy.

#### Scenario: A production branch runs only on a worker

- **WHEN** the coverage command executes a production branch in a distributed worker
- **THEN** the combined report records that branch as executed

#### Scenario: Parallel coverage misses a required branch

- **WHEN** the combined worker report falls below the configured coverage threshold
- **THEN** the coverage command fails without lowering the threshold or adding exclusions

#### Scenario: The serial baseline is compared

- **WHEN** serial and parallel full-suite coverage use identical inputs
- **THEN** they measure the same production files and retain the same coverage policy
