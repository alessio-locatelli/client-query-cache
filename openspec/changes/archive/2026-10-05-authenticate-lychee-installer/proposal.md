# Proposal

## Why

The Prek jobs on PRs #159 and #160 fail before link checking because Lychee's binary installer receives an unauthenticated GitHub Releases API 403 and its source fallback cannot use `--install-path`. Required link validation must work on runners without a populated hook cache.

## What Changes

- Run the existing Lychee hook separately within the Prek job, with GitHub's read-only job token available to its binary installer through `GH_TOKEN`.
- Keep the other hooks in their existing invocation without that credential.
- Document the installation authentication and cache behavior in the contributor cache inventory.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `continuous-integration`: Authenticate Lychee release installation within its validation step while preserving required checks on cache misses.

## Impact

Changes `.github/workflows/test.yml`, contributor documentation, and the CI specification. No library API, tool pin, accepted link status, job dependency, or permission changes are required.
