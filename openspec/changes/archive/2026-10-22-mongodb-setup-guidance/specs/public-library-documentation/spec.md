## ADDED Requirements

### Requirement: Quick start links local MongoDB setup

The README SHALL link local MongoDB setup before its executable example. The example SHALL use native PyMongo operations without custom connection-error handling.

#### Scenario: A reader prepares the quick start

- **WHEN** a reader reaches the README example
- **THEN** they can follow the single-member replica-set setup before running it

### Requirement: CI adopters can initialize disposable replica sets

The public guides SHALL provide replica-set setup fragments for existing GitLab Docker-executor and GitHub-hosted Ubuntu test jobs using digest-pinned MongoDB services and a shared PyMongo initializer. Initialization SHALL use explicit single-member configuration, bound readiness waits, succeed on repeated runs, and fail visibly on unavailable or unwritable servers. Tests SHALL begin only after a primary is writable.

#### Scenario: A fresh CI job starts

- **WHEN** an adopter follows either provider example
- **THEN** the initializer reaches a writable replica set and tests use the documented job-reachable connection string

#### Scenario: Initialization is repeated or cannot complete

- **WHEN** the initializer is repeated against the initialized service or the service is unavailable
- **THEN** it respectively succeeds without reinitialization or exits unsuccessfully within its deadline
