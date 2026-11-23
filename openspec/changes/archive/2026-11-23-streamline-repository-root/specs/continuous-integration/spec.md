# Continuous integration delta

## MODIFIED Requirements

### Requirement: CI runs database-backed tests in an owned runtime

GitHub Actions SHALL run integration and end-to-end tests using Docker and the disposable replica-set fixture when a pull request changes Python files, `pyproject.toml`, or `uv.lock`. It SHALL retain safe diagnostic artifacts on failure and SHALL not depend on a shared external database.

#### Scenario: A cache change is proposed

- **WHEN** a pull request changes a Python file
- **THEN** the Docker-backed job executes the integration and end-to-end test tiers before reporting success

#### Scenario: A documentation-only change is proposed

- **WHEN** a pull request changes only files outside the Python-validation path set
- **THEN** the Docker-backed job is not started

#### Scenario: A database-backed test fails

- **WHEN** an integration or end-to-end test fails in the hosted test job
- **THEN** the job uploads the available controller log and any separate worker logs for that run
