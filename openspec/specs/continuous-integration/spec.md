# continuous-integration Specification

## Purpose

This capability gives external contributors hosted, repeatable evidence that the locked project and its database-backed test tiers work together.

## Requirements

### Requirement: Every pull request runs basic quality gates

GitHub Actions SHALL run Prek and Justfile formatting validation for every pull request, and formatting checks when supported files change.

#### Scenario: A documentation file changes

- **WHEN** a pull request changes only Markdown files
- **THEN** Prek and the formatting workflow run, and the Python-validation workflow does not run

### Requirement: CI rejects unlocked dependencies

When the Python gate runs, CI SHALL synchronize committed `uv.lock` without modification.

#### Scenario: Dependency metadata is unlocked

- **WHEN** a change modifies dependency metadata without the corresponding lockfile update
- **THEN** the Python-validation workflow fails before accepting the change

### Requirement: Python changes run build and test gates

Python, pytest, project-metadata, or lockfile changes SHALL run static checks, build source and wheel distributions, install the wheel in isolation, and test CPython 3.14.

#### Scenario: A Python file changes

- **WHEN** a pull request changes a Python file
- **THEN** the Python-validation workflow runs the static checks and package-artifact validation

### Requirement: CI runs database-backed tests in an owned runtime

GitHub Actions SHALL run integration and end-to-end tests using Docker and the disposable replica-set
fixture when a pull request changes Python files, `pytest.ini`, `pyproject.toml`, or `uv.lock`. It SHALL
retain safe diagnostic artifacts on failure and SHALL not depend on a shared external database.

#### Scenario: A cache change is proposed

- **WHEN** a pull request changes a Python file
- **THEN** the Docker-backed workflow executes the integration and end-to-end test tiers before reporting
  success

#### Scenario: A documentation-only change is proposed

- **WHEN** a pull request changes only files outside the Python-validation path set
- **THEN** the Docker-backed workflow is not started

### Requirement: CI preserves reusable validation caches

GitHub Actions SHALL restore and save reusable caches produced by validation tools across compatible runs. Cache keys SHALL prevent reuse across incompatible toolchains or dependency sets, while allowing later commits to reuse prior compatible cache entries. Validation results SHALL remain authoritative when a cache is absent or stale.

#### Scenario: A later pull request run checks unchanged inputs

- **WHEN** a validation job runs with a compatible toolchain and dependency set after an earlier run saved a cache
- **THEN** the job restores that cache and saves updated reusable state for a subsequent run

#### Scenario: A validation cache is unavailable

- **WHEN** a compatible cache cannot be restored
- **THEN** the validation job still runs the full required checks and reports their actual results
