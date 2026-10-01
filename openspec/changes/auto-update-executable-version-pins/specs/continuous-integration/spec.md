# Spec Delta

## ADDED Requirements

### Requirement: Executable pin changes validate affected consumers

Pull requests changing executable dependency configuration SHALL run validation of the affected consumers even when no Python source changes. MongoDB Testcontainers image updates SHALL run owned-runtime integration and end-to-end tests and a bounded isolated benchmark startup check. Development-container pin or download-integrity updates SHALL build the image and verify its declared tools. Python or shared Python-toolchain updates SHALL run package validation and database-backed tests. Expensive consumer checks SHALL wait for applicable quality checks.

#### Scenario: A MongoDB pin changes without Python source edits

- **WHEN** a pull request updates a configuration value consumed by the test and benchmark replica sets
- **THEN** CI runs database-backed tests and checks isolated benchmark startup under the selected image

#### Scenario: A development-container package changes

- **WHEN** a pull request updates a Containerfile package, base image, or Taplo download
- **THEN** CI builds that definition and verifies the pinned tools after applicable quality checks pass

#### Scenario: An interpreter selection changes

- **WHEN** a pull request updates an executable Python selection without changing Python source
- **THEN** package validation and database-backed tests run using the proposed interpreter and performance comparisons retain their matched-interpreter constraint

#### Scenario: An unrelated document changes

- **WHEN** a pull request changes only documentation unrelated to executable inputs
- **THEN** these additional consumer checks do not run
