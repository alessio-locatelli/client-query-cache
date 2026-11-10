# Proposal

## Why

[Issue #298](https://github.com/alessio-locatelli/client-query-cache/issues/298) addresses repeated feeds and counts losing useful cache entries under unrelated writes. The [completed research](../../../../docs/development/research/stream-assisted-invalidation.md) establishes a production implementation opportunity without justifying additional stream costs for every collection.

## What Changes

- Deliver both production features specified in `specs/selective-invalidation/spec.md`, with their public guidance and measured acceptance evidence.
- Reconcile existing generation, cursor-admission, compatibility, and stream-projection requirements with the narrower guards in the accompanying deltas.

## Capabilities

### New Capabilities

- `selective-invalidation`: Collection policy configuration, query eligibility, event-specific retention, resource bounds, and adoption guidance.

### Modified Capabilities

- `cache-core`: Namespace generation and compatible-source validation when a result has a selective guard.
- `cached-read-api`: Complete-consumption admission under the result's applicable guard.
- `change-stream-coherency`: Collection-scoped projected invalidation hints.

## Impact

The affected production seams are `native/shared-index/src/local_cache.rs`, native capture/node contracts and Python bindings, `_core/native.py`, shared read preparation, `_core/stream_events.py`, and the synchronous and asynchronous managers, collections, cursors, and stream supervisors. Public exports, `docs/user/reference/api.md`, usage and consistency guides, `context7.json`, and the existing invalidation research workload infrastructure also need updates. No new runtime dependency is expected.
