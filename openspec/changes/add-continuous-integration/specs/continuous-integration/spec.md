## Purpose

This capability gives external contributors hosted, repeatable evidence that the locked project and its database-backed test tiers work together.

## ADDED Requirements

### Requirement: CI verifies the locked package and local gates

GitHub Actions SHALL synchronize the committed `uv.lock` without modification, run the established quality checks, build source and wheel distributions, and install the wheel in an isolated environment. It SHALL test CPython 3.14.

#### Scenario: Dependency metadata is unlocked

- **WHEN** a change modifies dependency metadata without the corresponding lockfile update
- **THEN** the CI workflow fails before accepting the change

### Requirement: CI runs database-backed tests in an owned runtime

GitHub Actions SHALL run integration and end-to-end tests using Docker and the disposable replica-set fixture. It SHALL retain safe diagnostic artifacts on failure and SHALL not depend on a shared external database.

#### Scenario: A cache change is proposed

- **WHEN** CI runs for a change to the repository
- **THEN** the Docker-backed job executes the integration and end-to-end test tiers before reporting success
