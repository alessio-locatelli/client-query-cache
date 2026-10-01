# Proposal

## Why

The current `find_one` implementation bypasses filters that are neither an exact `_id` lookup nor a qualifying unique-key lookup, even though the durable specification and archived designs describe a generic bounded fallback. Users should be able to cache a safe single-document query without rewriting it as a list-returning `find` call.

## What Changes

- Add namespace-guarded caching for deterministic generic `find_one` filters, including compound predicates, empty filters, and negative results.
- Keep the optimized `_id` and discovered-unique-key paths and their existing mutation isolation, codec behavior, and generation guards.
- Add explicit keyword-only `sort` and `collation` parameters; represent their effective values in cache keys and honor collation in unique-index matching.
- Preserve direct execution for sessions, unsupported options, unsafe filters or projections, uncanonicalizable values, and ineligible collections or streams.
- Reconcile the bypass tests, specification, and user guidance with the implemented contract. This fills a design/implementation gap rather than restoring previously shipped generic caching.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cached-read-api`: complete generic single-document caching, explicit sort/collation semantics, and precise fallback behavior when unique-index matching is unavailable.

## Impact

Touches both collection implementations, shared read-shape/unique-key handling where needed, sync/async collection tests, and current public documentation. It reuses namespace storage and invalidation instead of creating another cache or stream. Unknown keyword options continue to execute through PyMongo. Diagnostics integration uses the established bypass recording seam and can be applied before or after `improve-public-cache-observability`.
