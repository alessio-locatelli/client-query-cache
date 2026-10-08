# Continuous Integration Spec Delta

## MODIFIED Requirements

### Requirement: Python changes run build and test gates

Python, pytest, project-metadata, or lockfile changes SHALL run static checks, build source and wheel distributions, install artifacts in isolation, and execute database-backed tests across the compatibility matrix defined by the development-environment specification. Both packaging and test jobs SHALL consume the same matrix. A failed lane SHALL fail the existing stable Python compatibility check.

#### Scenario: A Python file changes

- **WHEN** a pull request changes a Python file
- **THEN** every selected compatibility lane runs static checks and package-artifact validation

#### Scenario: Package eligibility is widened

- **WHEN** a pull request lowers the Python minimum
- **THEN** isolated artifact imports, native-cursor end-to-end programs, and real-server tests succeed on the earliest eligible patch before the change is accepted

#### Scenario: A Python 3.15 lane fails

- **WHEN** packaging or database-backed validation fails on Python 3.15 while the development lane succeeds
- **THEN** the existing Python compatibility check fails and blocks merging

## ADDED Requirements

### Requirement: Stable Python validation precedes advertised release support

A package release advertising Python 3.15 support SHALL require successful packaging, isolated-import, native-cursor, and real-server validation on stable CPython 3.15 for the release revision. Release acceptance SHALL record the full resolved interpreter version and tested commit. Release-candidate results SHALL NOT satisfy this gate; unavailable or failed stable validation SHALL block publication.

#### Scenario: The pinned catalogue or cache still selects a candidate

- **WHEN** the Python 3.15 lane passes on a release candidate
- **THEN** early compatibility evidence is available but publication advertising Python 3.15 support remains blocked until stable validation succeeds

#### Scenario: Stable validation succeeds for the release revision

- **WHEN** the required validation succeeds on stable CPython 3.15 for the revision being released
- **THEN** release acceptance records the full interpreter version and tested commit before publication approval
