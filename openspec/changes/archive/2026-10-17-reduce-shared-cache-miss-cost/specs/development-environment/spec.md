## ADDED Requirements

### Requirement: Public integrity digests do not create secret findings

The secret scanner SHALL use its built-in line-exclusion filter for exact JSON `binary_sha256` and `cargo_lock_sha256` fields containing 64 lowercase hexadecimal characters. These public reproducibility digests SHALL NOT require repeated per-report baseline entries. Other fields and scanner rules SHALL retain their existing checks.

#### Scenario: A registered environment records its build digests

- **WHEN** an environment JSON records a native binary or Cargo lockfile digest in the named fields
- **THEN** secret scanning excludes those exact digest lines and continues checking other content
