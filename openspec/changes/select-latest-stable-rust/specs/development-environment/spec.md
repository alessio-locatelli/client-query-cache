## ADDED Requirements

### Requirement: Native builds use one selected stable Rust release

A root rustup toolchain file SHALL select one exact stable Rust release with the minimal profile. Development, CI, release, and source-distribution builds SHALL compile native code with that release through rustup, independently of compilers preinstalled in their environment. The native crate SHALL NOT declare a minimum Rust version, and validation SHALL NOT add compatibility checks for other compiler releases.

#### Scenario: CI compiles native code

- **WHEN** a CI job builds or checks the native extension on a runner whose preinstalled Rust differs from the selection
- **THEN** it compiles with the selected release

#### Scenario: A source distribution is built

- **WHEN** a user with rustup builds the package from its source distribution
- **THEN** the build uses the selected release

### Requirement: Source builds omit development components

Native quality setup SHALL install the selected release with its formatting, lint, and coverage components. Builds that only compile the extension SHALL NOT install those components.

#### Scenario: A Python lane builds the extension

- **WHEN** a CI job compiles the native extension without running native quality checks
- **THEN** it provisions the selected release without formatting, lint, or coverage components

### Requirement: The contributor image defaults to the selected Rust release

The contributor image SHALL provide rustup with the selected release as its default, usable by a non-root contributor inside and outside the checkout without manual setup. A non-root contributor SHALL be able to install a newly selected release and development components without rebuilding the image.

#### Scenario: A contributor runs Rust tools outside the checkout

- **WHEN** a non-root contributor runs `rustc` or `cargo` outside the repository in the built image
- **THEN** the selected release runs without installing a toolchain

#### Scenario: The selection advances after the image was built

- **WHEN** a contributor builds native code in the checkout after the selected release changes
- **THEN** rustup installs the new selection inside the container on first use

## MODIFIED Requirements

### Requirement: Container image inputs are pinned

The contributor image SHALL pin its base digest and tools installed outside DNF. DNF SHALL install `bash`, `gcc`, `gh`, `just`, `rustup`, `uv`, and Node.js/npm on the `.node-version` major track from Fedora 44 without RPM pins. Contributor documentation SHALL explain the bots' RPM pin limitations, expected low development-tool breakage risk, and package variability across rebuilds.

#### Scenario: A contributor rebuilds the image

- **WHEN** the same image definition is rebuilt
- **THEN** its base image and tools installed outside DNF remain pinned, DNF resolves compatible package versions from Fedora 44 repositories while selecting the Node.js major track from the shared `.node-version`, and host bridge commands remain documented host prerequisites
