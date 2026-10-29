## MODIFIED Requirements

### Requirement: The development container provides the documented toolchain

Contributors SHALL be able to build a development container with the documented toolchain. Rust builds SHALL use the stable release selected in the root rustup toolchain file. Only that selected release is tested and supported. Fedora DNF packages SHALL be resolved from the selected Fedora release repositories, selecting the Node.js major track from the shared `.node-version`.

#### Scenario: A contributor builds the dev container image

- **WHEN** a contributor builds the container image from the documented definition
- **THEN** the resulting container has `gh`, `uv`, Node.js, npm, `prek`, `taplo`, `zizmor`, `just`, `rustc`, and `cargo` available on `PATH`, and Rust uses the selected toolchain

### Requirement: Container image inputs are pinned

The contributor image SHALL pin its base digest and tools installed outside DNF. DNF SHALL install `bash`, `gh`, `just`, `uv`, rustup, and Node.js/npm on the `.node-version` major track from Fedora 44 without RPM pins. Contributor documentation SHALL explain the bots' RPM pin limitations, expected low development-tool breakage risk, and package variability across rebuilds.

#### Scenario: A contributor rebuilds the image

- **WHEN** the same image definition is rebuilt
- **THEN** its base image and Rust toolchain remain pinned, DNF resolves compatible package versions from Fedora 44 repositories while selecting the Node.js major track from the shared `.node-version`, and host bridge commands remain documented host prerequisites

## ADDED Requirements

### Requirement: Stable Rust toolchain updates are reviewed

Development, CI and release builds SHALL use the root selected stable Rust toolchain. Dependabot SHALL check weekly for stable releases, including patches, and toolchain update pull requests SHALL require human acceptance after validation.

#### Scenario: A stable Rust release is published

- **WHEN** Dependabot checks the root versioned toolchain after a stable release is available
- **THEN** it can propose an update without changing the Cargo dependency schedule

#### Scenario: The toolchain selection changes

- **WHEN** a pull request changes the root toolchain file
- **THEN** CI selects Rust, Python extension, contributor image and ARM64 validation and does not automatically accept the update
