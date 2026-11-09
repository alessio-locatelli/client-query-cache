# production-library-scope Specification

## Purpose

Keep installed Python and native library implementations focused on application execution while distinguishing runtime facilities from source-only tests and build material.

## Requirements

### Requirement: Every library implementation has a production purpose

Installed library implementations and native runtime bindings SHALL support actual application behavior. Use solely by tests, benchmarks, research, profiling, or release training SHALL NOT justify retaining such code. Removing it SHALL include orphaned helpers, exports, type stubs, and dependencies. Source-only tests and model adapters excluded from runtime compilation SHALL NOT be treated as installed implementations.

#### Scenario: Only development tooling calls an implementation

- **WHEN** consumer tracing finds no production purpose for an installed implementation or runtime binding
- **THEN** that code and its orphaned library dependencies are deleted completely
- **AND** no reference copy, fallback backend, compatibility shim, or renamed duplicate is retained for comparison anywhere in the repository

#### Scenario: A Python callback serves native production execution

- **WHEN** native production code calls a Python helper for supported application inputs
- **THEN** that helper has a production purpose and its supported behavior is preserved
- **AND** a misleading reference-implementation name is corrected without introducing a second implementation

### Requirement: Verification exercises production contracts

Tests SHALL verify the production implementation against specified outcomes and invariants. They SHALL NOT require a duplicate cache engine or runtime bindings added solely for inspection, fault injection, or test setup. Test location SHALL NOT by itself require relocation when the test code is excluded from runtime compilation.

#### Scenario: A differential test loses its reference engine

- **WHEN** a test compares a native operation with the removed Python engine
- **THEN** meaningful contract coverage is expressed using expected results, bounded operation schedules, native resource lifecycle, or observable production behavior
- **AND** tests of removed implementation mechanics are deleted instead of preserving those mechanics

#### Scenario: A test needs private ownership or recency data

- **WHEN** an internal inspection binding has no production consumer
- **THEN** the binding is removed and the test verifies the required behavior without adding another test-only library interface

#### Scenario: Native unit and concurrency tests need access to internal source

- **WHEN** native tests exercise private production operations or substitute model synchronization
- **THEN** ordinary compile-time-only unit tests and model adapters can remain beside the production source without a different crate or module assembly
- **AND** no duplicate cache algorithm or test-only exported library API is introduced

### Requirement: Current tooling uses production interfaces

Maintained benchmarks and profile training SHALL run through production interfaces. Obsolete workloads SHALL be removed rather than keeping supporting runtime code in the library. Harness transport and fault injection SHALL NOT become installed library implementations or runtime bindings. Retained commands SHALL preserve visible errors and truthful measurement scope.

#### Scenario: A workload depends on a removed transport or engine

- **WHEN** a benchmark, research runner, or training workload requires a development-only library facility
- **THEN** it is converted to the applicable production operation or removed with its command references and dependent tests
- **AND** current commands cannot silently substitute a different workload under an old result label

#### Scenario: Profile training runs after cleanup

- **WHEN** a release trains the native extension without MongoDB
- **THEN** it exercises the retained production hot paths without restoring a removed binding or requiring a development-only library transport

### Requirement: Distribution contents and guidance identify the production architecture

Current source and wheel distributions SHALL expose the production application implementation and its required integration code. Public configuration and manager exports SHALL remain usable in both execution models. Current guides and active plans SHALL identify the actual production owner, and SHALL NOT direct development toward a removed engine or inspection API.

#### Scenario: An application installs a cleaned distribution

- **WHEN** it imports public configuration and creates local or shared cached managers
- **THEN** construction and supported reads, consistency, errors, telemetry, and resource ownership retain their existing contracts without loading a reference engine

#### Scenario: A contributor follows an active plan

- **WHEN** the plan modifies cache ownership, admission, or invalidation
- **THEN** its implementation locations, synchronization assumptions, and verification target the production native owners

### Requirement: Source archives distinguish build material from runtime contents

Source distributions SHALL be inspected separately from installed wheels. Required build tooling, native test sources, and compile-time model adapters SHALL NOT be classified as shipped runtime facilities merely because they appear in a source archive. Neither artifact SHALL contain a duplicate cache engine preserved for development comparisons.

#### Scenario: A source archive includes native unit tests

- **WHEN** an archive contains compile-time-only unit tests or model fixtures under the native source tree
- **THEN** those files can remain without relocation if ordinary application builds exclude them and no development-only runtime binding is retained
