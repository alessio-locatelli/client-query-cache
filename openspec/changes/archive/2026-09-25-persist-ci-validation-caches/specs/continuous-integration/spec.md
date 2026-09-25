# Spec Delta

## ADDED Requirements

### Requirement: CI preserves reusable validation caches

GitHub Actions SHALL restore and save reusable caches produced by validation tools across compatible runs. Cache keys SHALL prevent reuse across incompatible toolchains or dependency sets, while allowing later commits to reuse prior compatible cache entries. Validation results SHALL remain authoritative when a cache is absent or stale.

#### Scenario: A later pull request run checks unchanged inputs

- **WHEN** a validation job runs with a compatible toolchain and dependency set after an earlier run saved a cache
- **THEN** the job restores that cache and saves updated reusable state for a subsequent run

#### Scenario: A validation cache is unavailable

- **WHEN** a compatible cache cannot be restored
- **THEN** the validation job still runs the full required checks and reports their actual results
