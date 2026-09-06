## Purpose

This capability gives every contributor a reproducible local build, dependency, linting, and type-checking environment before feature work begins.

## ADDED Requirements

### Requirement: Contributors use a locked uv project

The repository SHALL use `uv` for dependency resolution, environments, and package builds, SHALL configure `uv_build` with `module-root = ""` for the existing flat `mongo_client_cache/` package, SHALL commit `uv.lock`, and SHALL support CPython 3.14+. Its published PyMongo dependency SHALL be `>=4.18,<5`, the latest published PyMongo release at the time of this greenfield project, which also supports the generally available native async API. Published runtime dependencies SHALL remain distinct from development tooling.

#### Scenario: A clean checkout is synchronized

- **WHEN** a contributor synchronizes all declared development groups with the locked command
- **THEN** the environment is created without changing the committed lockfile

#### Scenario: The minimum PyMongo version is exercised

- **WHEN** the project validates its declared PyMongo lower bound
- **THEN** it installs PyMongo 4.18, imports `AsyncMongoClient`, and runs the supported minimum-version checks successfully

### Requirement: Contributors can run complete local quality checks

The repository SHALL provide a pinned Prek configuration that checks repository hygiene, formatting, linting, dead code, static types, slots, supported text formats, and secrets. The configuration SHALL run every check, including Ruff-extra, under the CPython 3.14 package baseline. The complete local quality workflow SHALL also validate `pyproject.toml` and the committed `uv.lock` with equivalent `uv` locked-project checks in place of the existing Poetry-specific project check, without passing matched filenames to a filename-insensitive `uv` command.

#### Scenario: A complete quality run finds a violation

- **WHEN** a contributor runs the documented full quality command on a violating tracked file
- **THEN** the responsible check reports the violation and the command fails

#### Scenario: The locked project is out of date

- **WHEN** a contributor runs the complete local quality workflow after changing dependency metadata without regenerating `uv.lock`
- **THEN** the `uv` locked-project validation reports the mismatch and the workflow fails
