# Proposal

## Why

The move away from the inheritance-based prototype and the rename from `mongo-client-cache` are complete. Specifications, tests, and identifiers that still describe that history guard nothing a current user can reach, and one test now blocks reuse of a private module name. History belongs in archived changes and the Git log.

## What Changes

- Remove the `prototype-recovery` capability. The `cached-read-api` requirements "A cached read view accepts an existing PyMongo collection" and "Facades preserve caller-owned clients" already own its composition contract, and the migration document it required no longer exists.
- Drop the rename-migration duty, the former-name alias clause, and former-name wording from `project-identity`.
- Delete the removed-prototype import test and its Vulture allowlist entry, give the mixed cached and direct collection tests neutral names, and update the benchmark report schema identifiers to the current project name.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `prototype-recovery`: every requirement is removed.
- `project-identity`: requirements describe the current identity without rename history.

## Impact

Tests, `.vulture_whitelist`, two benchmark JSON schemas, and two main specifications change. Runtime behavior, public APIs, and user documentation are unchanged. Committed benchmark evidence keeps the package name recorded at measurement time.
