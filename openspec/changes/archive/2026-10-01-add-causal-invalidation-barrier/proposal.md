# Proposal

## Why

The requests-cache, Celery, and py-abac examples poll consumer results after a write because stream health does not prove that the write's invalidation has been applied. Applications need an explicit bounded operation with a verifiable causal boundary, rather than a sleep or a claim based on observing an unrelated event.

## What Changes

- Specify an opt-in per-manager, per-database barrier whose successful return proves all relevant invalidations through a validated write boundary have been applied.
- Establish a public-driver progress mechanism and its correctness proof before freezing the callable API or implementing it. Resolve idle streams, shared event timestamps, filtered events, transactions, sharded ordering, and stream recovery in that proof.
- Require equivalent sync/async semantics, finite deadlines, explicit errors, cancellation cleanup, and no catch-up work on ordinary cached reads.
- Describe the supported boundary acquisition path for acknowledged writes and explicitly reject cases in which an upstream library hides the information needed to establish causality.
- Provide runtime implementation, regression tests, measured resource costs, and current public guidance only after the proof gate succeeds. If no mechanism meets the constraints, report the concrete blocker in this active change without weakening its success guarantee or adding an unsafe API.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `change-stream-coherency`: opt-in causal barriers, boundary validation, completion ordering, and bounded lifecycle/failure semantics.

## Impact

Expected runtime scope is both managers and stream coordinators/supervisors, a shared boundary/progress representation, public error exports, sync/async real-server tests, and documentation/examples where a supported boundary is available. No automatic writes to marker collections, resume-token decoding, client replacement, or per-read synchronization is authorized by this design. The exact public method and proof mechanism remain deliberately gated; planning completion does not imply that proof has been obtained.
