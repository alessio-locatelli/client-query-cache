## MODIFIED Requirements

### Requirement: The development container provides the documented toolchain

Contributors SHALL be able to build a development container with the documented toolchain. Tools installed outside DNF SHALL use explicit versions; Fedora DNF packages SHALL be resolved from the selected Fedora release repositories, selecting the Node.js major track from the shared `.node-version`.

#### Scenario: A contributor builds the dev container image

- **WHEN** a contributor builds the container image from the documented definition
- **THEN** the resulting container has `gh`, `uv`, Node.js, npm, `prek`, `taplo`, `zizmor`, `just`, `rustc`, and `cargo` available on `PATH`, without further manual installation; tools installed outside DNF match their pinned versions and DNF packages follow Fedora 44 repositories with Node.js on the major track selected by `.node-version`

### Requirement: Container image inputs are pinned

The contributor image SHALL pin its base digest and tools installed outside DNF. DNF SHALL install `bash`, `gh`, `just`, `uv`, the Rust compiler and Cargo, and Node.js/npm on the `.node-version` major track from Fedora 44 without RPM pins. Contributor documentation SHALL explain the bots' RPM pin limitations, expected low development-tool breakage risk, and package variability across rebuilds.

#### Scenario: A contributor rebuilds the image

- **WHEN** the same image definition is rebuilt
- **THEN** its base image and tools installed outside DNF remain pinned, DNF resolves compatible package versions from Fedora 44 repositories while selecting the Node.js major track from the shared `.node-version`, and host bridge commands remain documented host prerequisites

## ADDED Requirements

### Requirement: In-repository native extensions build from locked sources

Synchronizing the development groups SHALL build every in-repository native extension from its committed sources and crate lockfile. A missing compiler toolchain SHALL fail synchronization visibly, and contributor documentation SHALL name the required toolchain with a reference to its official installation guide.

#### Scenario: A clean checkout is synchronized with Rust installed

- **WHEN** a contributor with the documented toolchain synchronizes all development groups using the locked command
- **THEN** the native extension is built from the committed crate lockfile and importable in the project environment, and the lockfiles are unchanged

#### Scenario: The compiler toolchain is missing

- **WHEN** a contributor without Cargo synchronizes the development groups
- **THEN** synchronization fails with an error naming the missing build tool
