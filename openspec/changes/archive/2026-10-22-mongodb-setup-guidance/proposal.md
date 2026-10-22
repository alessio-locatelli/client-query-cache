# Proposal

## Why

The README's first write fails with a raw server-selection timeout when MongoDB is absent. Adopters also lack CI examples for starting the replica set that caching requires.

## What Changes

Provide actionable setup diagnostics and CI onboarding under the requirements in the delta specs.

## Capabilities

### Modified Capabilities

- `public-library-documentation`: executable onboarding and disposable CI MongoDB setup.
- `change-stream-coherency`: actionable diagnostics for confirmed standalone-server startup failures.

## Impact

README, installation and CI guides, sync and async stream startup, and their regression coverage. No dependency or public API changes.
