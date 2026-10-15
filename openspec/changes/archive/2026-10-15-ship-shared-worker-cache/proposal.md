# Ship the first shared worker cache

## Why

Applications with several workers currently duplicate cached values and change streams. The Rust shared index provides a foundation, but applications cannot yet install and operate it through the public package.

## What Changes

- Deliver a supported public shared-cache mode with explicit process ownership.
- Package the native implementation with version 0.8.0 and provide release verification.
- Define the initial contract in `specs/shared-worker-cache/spec.md` and the architectural choices in `design.md`.
- Keep the parent delivery issue open through integration and release readiness, independently of research milestones.

## Capabilities

### New Capabilities

- `shared-worker-cache`: Shared reads, attachment, lifecycle, security and distribution.

### Modified Capabilities

None. Existing process-local managers retain their API.

## Impact

The benchmark implementation becomes an internal library component reused by research callers. Public exports, package construction, deployment guidance, release workflows and installed-artifact verification change together. MongoDB and production services are not modified.
