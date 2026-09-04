## Why

A green development workflow does not prove that the public distribution can be built, installed, imported, and versioned as a release artifact. Release verification must be explicit while publishing authority is intentionally absent.

## What Changes

- Add non-publishing release checks for source and wheel distributions, isolated installation, public imports, and version/tag consistency.
- Document the boundary between verification and a future credentialed publishing workflow.

## Capabilities

### New Capabilities

- `release-verification`: Non-publishing validation of distributable package artifacts.

### Modified Capabilities

- None.

## Impact

- Adds release-verification commands and CI coverage after the public API and CI workflows are complete.
