# Proposal

## Why

Warm cached reads can return committed data inside a PyMongo `session.bind()` transaction because the shared guard recognizes only explicit sessions. The adapter study reproduced this defect in both execution models on PyMongo 4.18.1 and 4.18.2; cold bound reads must also avoid admitting session-scoped results.

## What Changes

- Resolve bound-session context before cache lookup or admission for all six supported reads, retaining explicit-session precedence and native validation.
- Exercise warm and cold reads, transaction visibility, context exit, and ended or other-client contexts through public sync and async behavior.
- Clarify the existing session-bypass requirement and user guidance, and record the driver resolver dependency and measured guard cost.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cached-read-api`: Clarify that session bypass includes bound contexts and preserves native errors and explicit-session precedence.

## Impact

The shared read guard, both cached collection call sites, regression tests, consistency guidance, and changelog are affected. Public signatures and dependency bounds stay unchanged. This is a separate production correction; the adapter evaluation retains its research scope and resumes after the correction is reviewed and completed.
