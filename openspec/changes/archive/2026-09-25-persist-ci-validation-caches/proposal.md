# Proposal

## Why

Several CI checks write reusable caches that are discarded with each runner, so repeated pull requests redo avoidable dependency, analysis, and link-check work.

## What Changes

- Persist each reusable cache produced by CI validation jobs, including Lychee, Prettier, Ruff, MyPy, Pytest, and Hypothesis.
- Keep cache keys scoped to compatible toolchains and inputs, and restore prior snapshots across commits so new results can be saved.
- Document the CI command and cache inventory, including tools that do not produce reusable caches.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `continuous-integration`: CI preserves reusable validation caches across runs.

## Impact

GitHub Actions validation workflows and CI maintenance documentation. No library API changes.
