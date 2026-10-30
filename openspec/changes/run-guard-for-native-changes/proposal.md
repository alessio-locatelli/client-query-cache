# Proposal

## Why

Cached reads, admission, and invalidation run in the native extension under `native/`, which the cache hot-path guard measures. A pull request that changes only native sources or the crate's `Cargo.lock` skips the guard, so a native slowdown can merge without a timed comparison.

## What Changes

- Select the cache hot-path guard for every pull request that changes a file under `native/`, including the crate manifest and `Cargo.lock`.
- Name native code among the inputs in the guard's skip message and its development guide.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `performance-regression-guard`: Native code changes run the guard, and only pull requests without them can skip it.

## Impact

Guard path selection and its tests, the pull request validation workflow's skip message, and the performance guard development guide. Native-only pull requests spend one additional guard job.
