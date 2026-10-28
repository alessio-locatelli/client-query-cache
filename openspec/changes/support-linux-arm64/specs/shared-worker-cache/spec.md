# Spec Delta

## MODIFIED Requirements

### Requirement: Release distribution and guidance

The package SHALL include public shared APIs and the native index in one PyPI distribution, with Linux x86-64 and ARM64 glibc 2.28+ CPython 3.14+ wheels and a buildable locked-source sdist. Installed artifacts SHALL start the owner outside the checkout. Public guides and Context7 SHALL specify supported deployment, scope, consistency and cleanup, and provide reproducible performance evidence for public reads.

#### Scenario: Compiler-free application install

- **WHEN** a supported application installs the release wheel
- **THEN** it can attach sync and async workers without a Rust toolchain or benchmark package

#### Scenario: ARM64 application uses both cache modes

- **WHEN** a Linux ARM64/glibc application meets the documented Python, MongoDB and shared-host prerequisites
- **THEN** process-local and shared sync/async caching provide the same public contracts as Linux x86-64
