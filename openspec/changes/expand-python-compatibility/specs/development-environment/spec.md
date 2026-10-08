# Development Environment Spec Delta

## MODIFIED Requirements

### Requirement: The project supports CPython 3.14 and newer

The project SHALL declare `requires-python = ">=3.14"` without a Python upper bound. `.python-version` SHALL select the exact default development interpreter, maintained by Renovate on stable releases without a repository release-line cap. CI SHALL exercise the earliest eligible patch, treating an omitted minimum patch as zero, and the exact selected development interpreter.

#### Scenario: Development advances to Python 3.15

- **WHEN** Renovate updates `.python-version` to a stable Python 3.15 release
- **THEN** development uses that exact release and CI validates Python 3.14.0 and the selected 3.15 release without raising the package minimum

#### Scenario: Development matches the exact package minimum

- **WHEN** the selected development interpreter equals the earliest eligible patch
- **THEN** CI runs one lane for that exact interpreter alongside any other supported release lines

#### Scenario: Development advances within the minimum release line

- **WHEN** development advances to another patch within Python 3.14
- **THEN** CI retains separate exact 3.14.0 and selected-development lanes

## ADDED Requirements

### Requirement: Declared Python release lines drive compatibility coverage

Package metadata SHALL list Python 3.14 and 3.15 version classifiers. CI SHALL cover every release line from the minimum through the highest classified or selected development line, even when development uses an older line. Lines represented by the exact minimum or development requests SHALL need no additional floating request; remaining lines SHALL use major/minor requests. Only identical emitted requests SHALL be deduplicated.

#### Scenario: Python 3.15 is tested before development advances

- **WHEN** metadata lists Python 3.14 and 3.15 and development selects 3.14.6
- **THEN** CI emits `3.14.0`, `3.15`, and `3.14.6`

#### Scenario: Development advances beyond the classified lines

- **WHEN** development selects 3.16.0 while metadata lists Python 3.14 and 3.15
- **THEN** CI emits `3.14.0`, `3.15`, and `3.16.0`

#### Scenario: Python 3.15 has only a downloadable release candidate

- **WHEN** the CI toolchain provides a Python 3.15 release candidate and no stable 3.15 download
- **THEN** the 3.15 lane runs on that candidate without changing the stable development selection

#### Scenario: Stable Python 3.15 becomes downloadable

- **WHEN** the CI toolchain provides a stable 3.15 download on a fresh runner
- **THEN** the 3.15 request selects a stable interpreter without retaining a separate release-candidate lane
