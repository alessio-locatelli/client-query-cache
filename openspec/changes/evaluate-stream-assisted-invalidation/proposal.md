# Proposal

## Why

[Issue #257](https://github.com/alessio-locatelli/client-query-cache/issues/257) asks whether insert partitions and update dependencies justify expanding the routing-only change stream. Modeled hit shares do not establish overall resource savings.

## What Changes

- Add a reproducible, isolated projection-cost experiment and a decision report linked from the existing invalidation research.
- Extend the transport evidence with independent end-to-end research guards and a measured net-benefit decision for each bounded policy.

## Capabilities

No public behavior or existing requirement changes. This research-only change sets `skip_specs: true`.

## Impact

Standalone tooling under `research/invalidation_scope/` and maintainer research documentation. Experimental adapters exercise the native cache and stream in disposable environments; production library behavior remains unchanged unless the evidence justifies adoption under the issue's constraints.
