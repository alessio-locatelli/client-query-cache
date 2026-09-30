# Spec Delta

## MODIFIED Requirements

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

## ADDED Requirements

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
