# continuous-integration Specification

## Purpose

This capability gives external contributors hosted, repeatable evidence that the locked project and its database-backed test tiers work together.

## Requirements

### Requirement: Every pull request runs basic quality gates

GitHub Actions SHALL run Prek and Justfile formatting validation for every pull request, and formatting checks when supported files change.

#### Scenario: A documentation file changes

- **WHEN** a pull request changes only Markdown files
- **THEN** the Prek and formatting jobs run, and the Python package and test jobs do not run

### Requirement: CI rejects unlocked dependencies

When the Python gate runs, CI SHALL synchronize committed `uv.lock` without modification.

#### Scenario: Dependency metadata is unlocked

- **WHEN** a change modifies dependency metadata without the corresponding lockfile update
- **THEN** the Python package job fails before accepting the change

### Requirement: Python changes run build and test gates

Python, pytest, project-metadata, or lockfile changes SHALL run static checks, build source and wheel distributions, install the wheel in isolation, and test CPython 3.14.

#### Scenario: A Python file changes

- **WHEN** a pull request changes a Python file
- **THEN** the Python package job runs the static checks and package-artifact validation

### Requirement: CI runs database-backed tests in an owned runtime

GitHub Actions SHALL run integration and end-to-end tests using Docker and the disposable replica-set
fixture when a pull request changes Python files, `pytest.ini`, `pyproject.toml`, or `uv.lock`. It SHALL
retain safe diagnostic artifacts on failure and SHALL not depend on a shared external database.

#### Scenario: A cache change is proposed

- **WHEN** a pull request changes a Python file
- **THEN** the Docker-backed job executes the integration and end-to-end test tiers before reporting
  success

#### Scenario: A documentation-only change is proposed

- **WHEN** a pull request changes only files outside the Python-validation path set
- **THEN** the Docker-backed job is not started

### Requirement: Expensive pull request validation waits for quality checks

GitHub Actions SHALL complete applicable linting and formatting checks successfully before starting package validation, database-backed tests, or the pull request performance comparison. Those expensive checks SHALL be skipped when a required quality check fails. Independent checks within each stage SHALL remain able to run concurrently.

#### Scenario: Linting fails on a Python change

- **WHEN** a pull request changes Python code and its linting check fails
- **THEN** package validation, database-backed tests, and the performance comparison do not start

#### Scenario: Formatting fails on a Python change

- **WHEN** a pull request changes Python code and a supported formatting input, and formatting fails
- **THEN** package validation, database-backed tests, and the performance comparison do not start

#### Scenario: Quality checks pass

- **WHEN** applicable quality checks pass on a Python change
- **THEN** package validation, database-backed tests, and the performance comparison can start concurrently

### Requirement: CI preserves reusable validation caches

GitHub Actions SHALL restore and save reusable caches produced by validation tools across compatible runs. Cache keys SHALL prevent reuse across incompatible toolchains or dependency sets, while allowing later commits to reuse prior compatible cache entries. Validation results SHALL remain authoritative when a cache is absent or stale.

#### Scenario: A later pull request run checks unchanged inputs

- **WHEN** a validation job runs with a compatible toolchain and dependency set after an earlier run saved a cache
- **THEN** the job restores that cache and saves updated reusable state for a subsequent run

#### Scenario: A validation cache is unavailable

- **WHEN** a compatible cache cannot be restored
- **THEN** the validation job still runs the full required checks and reports their actual results

### Requirement: Executable pin changes validate affected consumers

Pull requests changing executable dependency configuration SHALL run validation of the affected consumers even when no Python source changes. MongoDB Testcontainers image updates SHALL run owned-runtime integration and end-to-end tests and a bounded isolated benchmark startup check. Development-container pin or download-integrity updates SHALL build the image and verify its declared tools. Python or shared Python-toolchain updates SHALL run package validation and database-backed tests. Expensive consumer checks SHALL wait for applicable quality checks.

#### Scenario: A MongoDB pin changes without Python source edits

- **WHEN** a pull request updates a configuration value consumed by the test and benchmark replica sets
- **THEN** CI runs database-backed tests and checks isolated benchmark startup under the selected image

#### Scenario: A development-container package changes

- **WHEN** a pull request updates a Containerfile package, base image, or Taplo download
- **THEN** CI builds that definition and verifies the pinned tools after applicable quality checks pass

#### Scenario: An interpreter selection changes

- **WHEN** a pull request updates an executable Python selection without changing Python source
- **THEN** package validation and database-backed tests run using the proposed interpreter and performance comparisons retain their matched-interpreter constraint

#### Scenario: An unrelated document changes

- **WHEN** a pull request changes only documentation unrelated to executable inputs
- **THEN** these additional consumer checks do not run
