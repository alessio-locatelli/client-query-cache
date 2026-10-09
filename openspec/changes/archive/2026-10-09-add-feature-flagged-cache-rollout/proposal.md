# Proposal

## Why

[Issue #198](https://github.com/alessio-locatelli/client-query-cache/issues/198) asks for executable deployment-controlled rollout guidance beyond the existing rollback reference. Applications need evidence that their storage selection preserves tenant and authorization boundaries.

## What Changes

- Extend the catalogue application with one feature-flagged rollout scenario.
- Add a short extension to its canonical guide and a deployment-guide link.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `usage-examples`: application-controlled content-read selection, rollback evidence, and rollout observations.

## Impact

The catalogue script and hosted guide, plus the existing deployment guide. Delivery uses the existing example verification and ephemeral dependencies; package APIs, dependency manifests, and CI architecture are unaffected. See design.md for the prerequisite and integration decisions.
