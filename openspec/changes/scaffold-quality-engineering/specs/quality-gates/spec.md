## Purpose

Contributors need one reproducible set of source, configuration, documentation, and secret checks before changes enter the public library.

## ADDED Requirements

### Requirement: The repository provides reproducible local quality gates
The repository SHALL provide a pinned Prek configuration and documented `uv` commands that validate formatting, repository hygiene, Ruff, Ruff-extra rules, Vulture, mypy, slotscheck, Prettier, and secret detection. The quality configuration SHALL use the project's supported Python baseline for package analysis and SHALL not require a contributor to install Poetry.

#### Scenario: A contributor validates a complete checkout
- **WHEN** a contributor runs the documented full quality command in a clean checkout with `uv` available
- **THEN** it executes every configured quality check against tracked project content and returns a nonzero status for a violation

#### Scenario: Ruff-extra requires a newer hook interpreter
- **WHEN** the Ruff-extra hook requires Python 3.14 while the package supports Python 3.13+
- **THEN** the hook runs in an isolated compatible hook environment and the package runtime requirement remains Python 3.13+

### Requirement: Quality tooling does not conceal defects
The repository SHALL configure analysis tools to fail on detected violations and SHALL not suppress production-code warnings or coverage-relevant code merely to make a gate pass. Documented exclusions SHALL state their narrow reason.

#### Scenario: A seeded source-quality defect is checked
- **WHEN** a supported quality tool is run against a file containing a violation that the tool detects
- **THEN** the command reports the violation and exits unsuccessfully
