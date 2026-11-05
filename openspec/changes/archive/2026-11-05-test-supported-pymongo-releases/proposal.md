# Proposal

## Why

The core depends on PyMongo's private interfaces, yet CI exercises only two driver versions: the locked one and the declared minimum. Dependabot refreshes the lockfile monthly (`docs/development/executable-version-updates.md`), so releases published in between, such as 4.18.2 and 4.18.3 today, are never tested. An incompatible release then surfaces in adopters' environments first. A lockfile stays the right practice for adopters, but it does not widen what the project itself verifies.

## What Changes

- The existing minimum-driver CI job also runs the minimum check's behavioral tests against the other supported PyMongo releases, with a Just recipe for contributors to run the same check locally.

Out of scope: running the full suite per release, testing releases outside the declared range, changing the declared minimum, and any public API or user-facing documentation change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `development-environment`: Adds the requirement that every supported PyMongo release is exercised.
- `continuous-integration`: Adds the requirement that the release check runs in the existing minimum-driver job and feeds the stable compatibility gate.

## Impact

CI configuration, contributor tooling and documentation, and tests.
