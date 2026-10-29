## MODIFIED Requirements

### Requirement: Executable pin changes validate affected consumers

Pull requests changing executable dependency configuration SHALL validate the affected consumers even when no Python source changes. Expensive consumer checks SHALL wait for applicable quality checks.

#### Scenario: A MongoDB pin changes without Python source edits

- **WHEN** a pull request updates a configuration value consumed by the test and benchmark replica sets
- **THEN** CI runs owned-runtime integration and end-to-end tests and a bounded isolated benchmark startup check under the selected image after applicable quality checks pass

#### Scenario: A development-container package changes

- **WHEN** a pull request updates a Containerfile package, base image, Taplo download, or download-integrity value
- **THEN** CI builds that definition and verifies the pinned tools after applicable quality checks pass

#### Scenario: An interpreter selection changes

- **WHEN** a pull request updates an executable Python selection without changing Python source
- **THEN** package validation and database-backed tests run using the proposed interpreter and performance comparisons retain their matched-interpreter constraint

#### Scenario: Shared Python-toolchain configuration changes

- **WHEN** a pull request updates shared Python-toolchain configuration without changing Python source
- **THEN** package validation and database-backed tests run after applicable quality checks pass

#### Scenario: The Rust toolchain selection changes

- **WHEN** a pull request changes only the selected Rust release
- **THEN** CI runs native static checks, native tests and concurrency models, package validation and database-backed tests, ARM64 runtime and distribution checks, the development-container check, and the performance guard after applicable quality checks pass

#### Scenario: An unrelated document changes

- **WHEN** a pull request changes only documentation unrelated to executable inputs
- **THEN** these additional consumer checks do not run
