## Purpose

This capability gives every contributor a reproducible local build, dependency, linting, and type-checking environment before feature work begins.

## ADDED Requirements

### Requirement: Contributors use a locked uv project
The repository SHALL use `uv` for dependency resolution, environments, and package builds, SHALL configure `uv_build` with `module-root = ""` for the existing flat `mongo_client_cache/` package, SHALL commit `uv.lock`, and SHALL support CPython 3.13+. Its published PyMongo dependency SHALL be `>=4.13,<5` so the declared runtime supports the generally available native async API. Published runtime dependencies SHALL remain distinct from development tooling.

#### Scenario: A clean checkout is synchronized
- **WHEN** a contributor synchronizes all declared development groups with the locked command
- **THEN** the environment is created without changing the committed lockfile

#### Scenario: The minimum PyMongo version is exercised
- **WHEN** the project validates its declared PyMongo lower bound
- **THEN** it installs PyMongo 4.13, imports `AsyncMongoClient`, and runs the supported minimum-version checks successfully

### Requirement: Contributors can run complete local quality checks
The repository SHALL provide a pinned Prek configuration that checks repository hygiene, formatting, linting, dead code, static types, slots, supported text formats, and secrets. The configuration SHALL retain the Python 3.13 package baseline when a check uses an isolated newer interpreter.

#### Scenario: A complete quality run finds a violation
- **WHEN** a contributor runs the documented full quality command on a violating tracked file
- **THEN** the responsible check reports the violation and the command fails
