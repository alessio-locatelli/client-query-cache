# Proposal

## Why

Issue #31's individual invariants have regression coverage, but no real-server workload combines sustained reads, external CRUD, and controlled recovery races. Performance and sequential memory tests do not establish concurrent correctness.

## What Changes

- Add a reproducible mixed CRUD integration workload for synchronous threads and asynchronous tasks, with one manager and hot/cold collections per run.
- Check freshness against processed invalidations, negative-result invalidation, and stale admission rejection during active traffic.
- Exercise lost-history recovery while reads are in flight and verify cache lookup and admission remain disabled during uncertainty.
- Document bounded CI defaults and longer local runs using existing pytest timeout and the cycle-count option.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `test-environment`: Require bounded, reproducible mixed concurrency correctness coverage against disposable MongoDB.

## Impact

Integration tests and shared test support, a pytest stress-cycle option, and contributor documentation. No public API or runtime dependency changes. The existing replica-set fixture supplies the database; no live deployment is used.
