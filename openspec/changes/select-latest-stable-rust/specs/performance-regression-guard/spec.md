## MODIFIED Requirements

### Requirement: Relevant pull requests run the cache hot-path guard

CI SHALL run a bounded sync and asyncio cache-hit, admission, and invalidation guard for changes affecting Python code, runtime dependencies, the selected Rust toolchain, or guard inputs.

#### Scenario: A Python change affects a shared cache path

- **WHEN** a pull request changes Python code that may affect cached reads or invalidation
- **THEN** CI measures the guarded paths for the base and proposed revisions and reports a guard result

#### Scenario: The compiler selection changes

- **WHEN** a pull request changes only the selected Rust release
- **THEN** CI measures the guarded paths with each revision built by its own selected compiler and reports a guard result

#### Scenario: A case never exercises its claimed cache outcome

- **WHEN** a timed case does not produce its required hit, admission, or invalidation outcome
- **THEN** its measurement is rejected rather than compared as valid performance evidence
