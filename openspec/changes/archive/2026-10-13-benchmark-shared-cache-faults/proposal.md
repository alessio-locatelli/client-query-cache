# Proposal

## Why

[Issue #273](https://github.com/alessio-locatelli/client-query-cache/issues/273) identifies missing timed fault evidence in the shared-worker study. Its deterministic safety scenarios do not establish recovery durations.

## What Changes

- Add an executable registered fault phase and case-level timing and safety analysis.
- Preserve frozen registrations and introduce a dedicated shared-worker registration.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `shared-cache-benchmarking`: Registered fault applicability, timed observations and fail-closed outcomes.

## Impact

The research harness, reusable scenario checks, benchmark tests, research documentation and `reports/shared-worker-cache/v6/` change. The library's supported API does not change. The separate `benchmark-worker-fault-recovery` change retains ownership of direct and independent worker faults.
