## Purpose

GitHub Actions must give contributors repeatable evidence that a proposed public-library change meets the supported quality and runtime contracts.

## ADDED Requirements

### Requirement: Continuous integration verifies the locked project and package artifact
GitHub Actions SHALL verify that the committed `uv.lock` resolves without modification, run the configured quality gates, build both source and wheel distributions, and install the wheel into an isolated environment before reporting success. It SHALL test the supported CPython version range beginning at Python 3.13.

#### Scenario: A dependency declaration is not locked
- **WHEN** a change modifies project dependencies without updating the committed lockfile
- **THEN** the continuous-integration workflow fails before accepting the change

#### Scenario: A built wheel has an import defect
- **WHEN** the isolated wheel-install check cannot import the documented public package surface
- **THEN** the continuous-integration workflow fails

### Requirement: Continuous integration executes the appropriate test tiers
GitHub Actions SHALL run the unit and complete-coverage gates for every change and SHALL run database-backed integration and end-to-end suites in a Docker-capable job. The workflow SHALL retain coverage and relevant test artifacts on failure to support diagnosis without exposing credentials or document contents.

#### Scenario: A change affects cache behavior
- **WHEN** a continuous-integration run executes for a proposed change
- **THEN** its database-backed job exercises the disposable replica-set integration and end-to-end suites before reporting success
