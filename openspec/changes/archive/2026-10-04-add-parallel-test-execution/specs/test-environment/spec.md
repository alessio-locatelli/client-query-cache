# Spec Delta

## ADDED Requirements

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
