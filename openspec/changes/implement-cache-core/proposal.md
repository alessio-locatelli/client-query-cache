## Why

The public cache needs a bounded, race-safe local storage and lifecycle foundation before a change stream or read facade can safely admit data.

## What Changes

- Add manager contracts, cache identity, canonicalization, and lifecycle state.
- Add a shared weighted BSON LRU with value isolation, aliases, namespace clearing, and capacity inspection.
- Add safe cache health, capacity, and lifecycle observability.

## Capabilities

### New Capabilities

- `cache-core`: Bounded, inspectable, process-local cache storage and manager primitives.

### Modified Capabilities

- None.

## Impact

- Adds internal cache infrastructure and unit tests; it depends on `recover-proof-of-concept`.
