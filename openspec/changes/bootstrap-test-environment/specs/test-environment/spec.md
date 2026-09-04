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

### Requirement: Production branch coverage is complete
The repository SHALL measure branches for every importable production module and SHALL fail its coverage command unless the combined production result is 100 percent. Exclusions SHALL be limited to code that cannot execute on a supported runtime and SHALL explain why.

#### Scenario: A reachable branch is not covered
- **WHEN** a coverage run leaves a production branch unexecuted
- **THEN** the command fails and identifies the missing branch
