## Why

The existing tests require a manually managed MongoDB endpoint and do not separate fast unit feedback from replica-set integration or installed-package end-to-end evidence. Cache work needs an isolated test foundation before feature implementation.

## What Changes

- Add explicit pytest tiers, branch coverage, and a Testcontainers-owned single-node replica set.
- Replace fixed-port, shared-state test assumptions with isolated clients and namespaces.
- Add a clean-wheel end-to-end harness and Docker/Podman contributor guidance.

## Capabilities

### New Capabilities

- `test-environment`: Reproducible unit, integration, end-to-end, and coverage execution environments.

### Modified Capabilities

- None.

## Impact

- Affects test configuration, fixtures, coverage settings, and contributor documentation; it depends on `bootstrap-development-environment`.
