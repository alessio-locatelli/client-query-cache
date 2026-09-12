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
