# Spec Delta

## MODIFIED Requirements

### Requirement: The development container provides the documented toolchain

Contributors SHALL be able to build a development container with the documented toolchain. Tools installed outside DNF SHALL use explicit versions; Fedora DNF packages SHALL be resolved from the selected Fedora release repositories, selecting the Node.js major track from the shared `.node-version`.

#### Scenario: A contributor builds the dev container image

- **WHEN** a contributor builds the container image from the documented definition
- **THEN** the resulting container has `uv`, Node.js, npm, `prek`, `taplo`, `zizmor`, and `just` available on `PATH`, without further manual installation; tools installed outside DNF match their pinned versions and DNF packages follow Fedora 44 repositories with Node.js on the major track selected by `.node-version`

### Requirement: Container image inputs are pinned

The contributor image SHALL pin its base digest and tools installed outside DNF. DNF SHALL install `bash`, `just`, `uv`, and Node.js/npm on the `.node-version` major track from Fedora 44 without RPM pins. Contributor documentation SHALL explain the bots' RPM pin limitations, expected low development-tool breakage risk, and package variability across rebuilds.

#### Scenario: A contributor rebuilds the image

- **WHEN** the same image definition is rebuilt
- **THEN** its base image and tools installed outside DNF remain pinned, DNF resolves compatible package versions from Fedora 44 repositories while selecting the Node.js major track from the shared `.node-version`, and host bridge commands remain documented host prerequisites

### Requirement: The project supports CPython 3.14 and newer

The project SHALL retain CPython 3.14 and newer compatibility. `.python-version` SHALL select the exact default development interpreter, maintained by Renovate on stable releases without a repository release-line cap. CI SHALL retain the exact declared minimum Python patch, test intermediate supported release lines, and test the exact selected development interpreter. Only identical interpreter requests SHALL be deduplicated.

#### Scenario: Development advances to Python 3.15

- **WHEN** Renovate updates `.python-version` to a stable Python 3.15 release
- **THEN** development uses that exact release and CI validates the exact declared minimum Python 3.14 patch and the selected 3.15 release without raising the package minimum

#### Scenario: Development matches the exact package minimum

- **WHEN** the selected development interpreter equals the exact declared package minimum
- **THEN** CI runs one lane on that exact interpreter

#### Scenario: Development advances within the minimum release line

- **WHEN** the declared package minimum is 3.14.6 and development advances to 3.14.7
- **THEN** CI retains separate exact 3.14.6 and 3.14.7 lanes

### Requirement: Local quality checks cover the declared tool set

The pinned Prek workflow SHALL check repository hygiene, formatting, linting, dead code, static types, slots, supported text formats, and secrets. Python hook environments SHALL retain the supported CPython 3.14 baseline independently of the development interpreter, using Prek's managed interpreter installation. Project packaging and test checks SHALL run across the CI compatibility matrix.

#### Scenario: A contributor runs all hooks

- **WHEN** the complete local quality workflow invokes Prek, including Ruff-extra
- **THEN** Python hooks use the supported CPython 3.14 baseline, while project checks use their selected development or compatibility-lane interpreter
