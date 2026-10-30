## MODIFIED Requirements

### Requirement: Relevant pull requests run the cache hot-path guard

CI SHALL run a bounded sync and asyncio cache-hit, admission, and invalidation guard for changes affecting Python code, native code, runtime dependencies, the selected Rust toolchain, or guard inputs.

#### Scenario: A Python change affects a shared cache path

- **WHEN** a pull request changes Python code that may affect cached reads or invalidation
- **THEN** CI measures the guarded paths for the base and proposed revisions and reports a guard result

#### Scenario: A native change affects a cache path

- **WHEN** a pull request changes only native sources, the native crate manifest, or its dependency lockfile
- **THEN** CI measures the guarded paths with each revision's own native extension and reports a guard result

#### Scenario: The compiler selection changes

- **WHEN** a pull request changes only the selected Rust release
- **THEN** CI measures the guarded paths with each revision built by its own selected compiler and reports a guard result

#### Scenario: A case never exercises its claimed cache outcome

- **WHEN** a timed case does not produce its required hit, admission, or invalidation outcome
- **THEN** its measurement is rejected rather than compared as valid performance evidence

### Requirement: Unaffected pull requests keep a stable guard status

CI SHALL provide a stable guard status for pull requests that do not affect its inputs.

#### Scenario: A documentation-only change is proposed

- **WHEN** a pull request changes no Python code, native code, Python runtime dependency, or guard input
- **THEN** the guard reports a successful, explicit skip without running timed workloads
