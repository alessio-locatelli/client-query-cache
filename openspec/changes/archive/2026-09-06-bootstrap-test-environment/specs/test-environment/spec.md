## Purpose

This capability provides isolated test tiers that verify MongoDB behavior without requiring a contributor-owned database or container runtime for unit tests.

## ADDED Requirements

### Requirement: Tests have explicit execution tiers

The repository SHALL label unit, integration, end-to-end, and benchmark tests. Unit tests SHALL not require a container runtime. Integration tests SHALL use a disposable MongoDB replica set. End-to-end tests SHALL install the built package in a clean environment and exercise the public API with an independent raw writer.

#### Scenario: A contributor runs unit tests without MongoDB

- **WHEN** a contributor runs the documented unit command on a machine without Docker, Podman, or MongoDB
- **THEN** only non-database tests run and the command does not attempt a database connection

### Requirement: Database-backed tests own their topology

Database-backed tests SHALL initialize and wait for a disposable single-node MongoDB replica set with dynamically allocated endpoints. They SHALL not use a fixed Compose port, a shared external database, or pre-existing collection state.

#### Scenario: An integration suite starts

- **WHEN** an integration suite runs with an accessible supported container runtime
- **THEN** it creates the replica set, waits for a writable primary, and cleans it up after the suite

### Requirement: Production branch coverage cannot regress

The repository SHALL measure branches for every importable production module and SHALL fail its coverage command below the recorded 81.10 percent combined production baseline. The repository SHALL NOT exclude ordinary production paths from measurement. The `implement-change-stream-coherency` change SHALL raise the threshold to 100 percent when it implements the planned cache-coherency operations.

#### Scenario: A reachable branch is not covered

- **WHEN** a coverage run leaves a production branch unexecuted
- **THEN** the report identifies the missing branch and the command fails if combined coverage falls below the recorded baseline

#### Scenario: Planned behavior remains unimplemented

- **WHEN** the baseline includes a production branch owned by `implement-change-stream-coherency`
- **THEN** the branch remains visible as missing coverage without a coverage exclusion
