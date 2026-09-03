## Purpose

The library needs repeatable test tiers that exercise cache behavior against the MongoDB topology required for change streams.

## ADDED Requirements

### Requirement: The repository separates unit, integration, and end-to-end tests
The repository SHALL label and document unit, integration, and end-to-end test suites. Unit tests SHALL run without a container runtime or MongoDB server. Integration tests SHALL use a test-owned MongoDB replica set. End-to-end tests SHALL exercise the built distribution through its public API in a clean environment and use an independent raw PyMongo writer to produce externally visible changes.

#### Scenario: A contributor runs the fast unit suite
- **WHEN** a contributor runs the documented unit-test command without Docker, Podman, or MongoDB installed
- **THEN** the command executes only tests that do not require a containerized MongoDB server

#### Scenario: An end-to-end test observes an external write
- **WHEN** the end-to-end suite warms a cached result and a separate raw PyMongo client changes the same collection
- **THEN** the test observes the documented cache-coherency behavior through the installed public package

### Requirement: Database-backed suites use a disposable replica set
Database-backed tests SHALL start an isolated, single-node MongoDB replica set with change streams available, wait until it has a writable primary, and clean it up after the test session. Tests SHALL use dynamically allocated endpoints and SHALL not depend on the repository's manually managed Compose port.

#### Scenario: An integration test starts its database
- **WHEN** the integration suite starts in an environment with the supported container runtime
- **THEN** it provisions a disposable single-node replica set, initializes it, waits for primary election, and provides the resolved connection information to tests

#### Scenario: A container runtime is unavailable
- **WHEN** a contributor requests an integration or end-to-end suite without an accessible supported container runtime
- **THEN** the test command fails or skips according to its documented explicit mode and explains that the MongoDB replica-set prerequisite is unavailable

### Requirement: Container-runtime support is explicit
The repository SHALL support Docker Engine as the continuous-integration container runtime and SHALL document a Docker API-compatible Podman configuration as a local-development alternative. The documentation SHALL state any Podman-specific Testcontainers configuration required by the supported setup and SHALL not claim equivalent behavior for unverified runtimes.

#### Scenario: Continuous integration runs database-backed tests
- **WHEN** the continuous-integration database-test job runs
- **THEN** it uses Docker Engine to run the disposable MongoDB replica set rather than relying on a shared external database
