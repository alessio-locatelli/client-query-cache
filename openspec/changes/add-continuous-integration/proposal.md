## Why

Local commands alone do not give external contributors consistent evidence that a change is locked, packaged, typed, tested, and exercised against a replica set. CI belongs after those local gates are established.

## What Changes

- Add GitHub Actions quality/build, unit/coverage, and Docker-backed integration/end-to-end jobs.
- Enforce locked `uv` resolution and isolated wheel installation.
- Upload diagnostic artifacts without credentials or document contents.

## Capabilities

### New Capabilities

- `continuous-integration`: Hosted verification of the established developer and test workflows.

### Modified Capabilities

- None.

## Impact

- Adds GitHub Actions workflows and depends on `bootstrap-development-environment` and `bootstrap-test-environment`.
