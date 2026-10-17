# Proposal

## Why

[Issue #257](https://github.com/alessio-locatelli/client-query-cache/issues/257) asks whether insert partitions and update dependencies justify expanding the routing-only change stream. Modeled hit shares do not establish overall resource savings.

## What Changes

- Add a reproducible, isolated projection-cost experiment and a decision report linked from the existing invalidation research.
- Evaluate the two policies independently before introducing any guard subsystem.

## Capabilities

No public behavior or existing requirement changes. This research-only change sets `skip_specs: true`.

## Impact

Standalone tooling under `research/invalidation_scope/` and maintainer research documentation. Runtime library code and production environments are outside this change.
