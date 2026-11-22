## ADDED Requirements

### Requirement: Top-level directories are conventional or tool-required

Tracked top-level directories SHALL be limited to `.agents`, `.claude`, `.github`, and `openspec`, which tools read from the repository root; the conventional `docs`, `src`, and `tests`; and `development`, which holds contributor tooling such as benchmarks, research harnesses, scripts, and lint rules. Reports, runnable examples, and the reference-specification submodule SHALL live under `docs`; native extension sources SHALL live under `src`.

#### Scenario: A contributor lists the repository root

- **WHEN** a contributor lists the tracked top-level directories of a checkout
- **THEN** exactly `.agents`, `.claude`, `.github`, `development`, `docs`, `openspec`, `src`, and `tests` appear

#### Scenario: A contributor runs a moved development tool

- **WHEN** a contributor runs a benchmark, research harness, or script through its documented command
- **THEN** the command names its location under `development` and runs from the repository root without extra import-path configuration

### Requirement: New top-level directories have a placement justification

A new tracked top-level directory SHALL be added only when a tool requires that location, or when it groups related files that no existing top-level directory fits. Content that fits an existing top-level directory SHALL be placed there.

#### Scenario: A contributor adds a new kind of development artifact

- **WHEN** a contributor adds files that serve contributor tooling or documentation
- **THEN** they are placed under `development` or `docs` rather than in a new top-level directory
