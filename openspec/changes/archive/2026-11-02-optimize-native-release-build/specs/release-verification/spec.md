# Spec Delta

## ADDED Requirements

### Requirement: Native extension builds use whole-program optimization

Every optimized build of the native extension, including editable installs, source-distribution builds and release wheels, SHALL compile it as one code-generation unit with whole-program link-time optimization.

#### Scenario: A source distribution is built

- **WHEN** an installer builds the extension from the source distribution
- **THEN** the extension is optimized as one unit across the crate and its dependencies without any additional configuration

### Requirement: Release wheels are profile-guided

The release build SHALL produce each wheel from an execution profile recorded on the building architecture: an instrumented build of the same revision runs the training workload, and the final wheel is compiled with that profile.

#### Scenario: A release is built on two architectures

- **WHEN** the release build runs on x86-64 and on ARM64 hosts
- **THEN** each wheel is compiled with a profile recorded natively on that host, and no profile is shared between architectures or stored in the repository

#### Scenario: A source distribution is built

- **WHEN** the release build produces the source distribution
- **THEN** the distribution contains no profile and building from it needs no profile tooling

### Requirement: Profile guidance never degrades silently

When the instrumented build, the training run, the profile merge or the final build fails, or the training run records no profile, the release build SHALL fail and SHALL NOT emit a wheel.

#### Scenario: Profile tooling is missing

- **WHEN** the Rust component that merges profiles is not installed
- **THEN** the release build fails with a message naming the missing component and writes no wheel

#### Scenario: The training run fails

- **WHEN** the training command exits with an error
- **THEN** the release build fails and writes no wheel

### Requirement: The training workload needs no database

The training workload SHALL run without MongoDB. It SHALL drive the native entry points used by cached reads, admissions, invalidation, key preparation and the shared index, so that no entry point on the cache hot path is absent from the profile.

#### Scenario: The training workload runs without a database

- **WHEN** the training workload runs against an installed build in an environment with no MongoDB server
- **THEN** it completes and exercises every workload it declares

#### Scenario: A native entry point changes its signature

- **WHEN** a change alters a native entry point that the training workload calls
- **THEN** the repository's test suite fails before a release build can be started
