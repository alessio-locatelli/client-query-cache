## MODIFIED Requirements

### Requirement: CI verifies the locked package and local gates

GitHub Actions SHALL run Prek and validate Justfile formatting for every pull request. It SHALL run
Prettier and Markdownlint when a pull request changes a file supported by the configured Prettier
invocation or its formatting configuration. It SHALL synchronize the committed `uv.lock` without
modification, run static Python checks, build source and wheel distributions, and install the wheel in an
isolated environment only when a pull request changes Python files, `pytest.ini`, `pyproject.toml`, or
`uv.lock`. It SHALL test CPython 3.14.

#### Scenario: A documentation file changes

- **WHEN** a pull request changes only Markdown files
- **THEN** Prek and the formatting workflow run, and the Python-validation workflow does not run

#### Scenario: Dependency metadata is unlocked

- **WHEN** a pull request modifies `pyproject.toml` without the corresponding lockfile update
- **THEN** the Python-validation workflow fails before accepting the change

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
