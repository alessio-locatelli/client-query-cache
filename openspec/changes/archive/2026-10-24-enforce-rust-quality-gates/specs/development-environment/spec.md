## ADDED Requirements

### Requirement: Native formatting is enforced

The local quality workflow SHALL reject Rust source that differs from the standard formatter. The formatting recipe SHALL repair those differences.

#### Scenario: Rust formatting differs

- **WHEN** a contributor checks an incorrectly formatted native source file
- **THEN** the quality command fails and the formatting command repairs the file

### Requirement: Native compiler and lint diagnostics fail validation

The native lint command SHALL reject compiler and Clippy warnings in the production Python-extension configuration and the concurrency-model configuration. Production dead-code and unused-import diagnostics SHALL NOT be suppressed wholesale. Configuration-specific exceptions SHALL state their reason beside the suppression.

#### Scenario: Unused production code is introduced

- **WHEN** a private unused function is added to the native extension
- **THEN** native linting fails

### Requirement: Native dependency policy is enforced

The local native quality workflow SHALL reject unused dependencies and unlinked Rust files, known dependency vulnerabilities, disallowed licenses, unapproved dependency sources, and duplicate dependency versions. Dependency-policy warnings SHALL fail validation.

#### Scenario: A dependency violates policy

- **WHEN** the native dependency graph violates the configured policy
- **THEN** native quality validation reports the violation and exits unsuccessfully
