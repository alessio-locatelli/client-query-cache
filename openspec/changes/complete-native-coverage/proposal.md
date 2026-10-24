# Proposal

## Why

Python coverage does not measure the native extension. Native static checks cannot establish whether Rust paths or Python binding bodies execute in tests.

## What Changes

- Add a native production coverage gate and remediate the gaps it exposes.
- Keep this work separate from native static enforcement, as tracked in [issue #328](https://github.com/alessio-locatelli/client-query-cache/issues/328).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `test-environment`: Native production coverage.
- `continuous-integration`: Native coverage execution after static checks.

## Impact

Native tests and any necessary testability changes, local coverage tooling, CI, and development documentation. Public cache behavior remains governed by its existing specifications.
