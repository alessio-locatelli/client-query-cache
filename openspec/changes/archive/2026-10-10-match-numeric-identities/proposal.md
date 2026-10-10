# Proposal

## Why

MongoDB compares numeric `_id` values by value across BSON types, so `find_one({"_id": 1})` matches a document stored with `_id: Decimal128("1")`. The change event for that document carries a `Decimal128`, which the cache cannot use as an identity key. The manager therefore skips identity routing for the event, and the cached result stays stale until the namespace is cleared or evicted. The same happens when a decimal appears anywhere inside an embedded `_id` document. An investigation of invalidation scope reproduced the defect.

## What Changes

- Identity keys and write routing treat `_id` values as equal when MongoDB compares them as numerically equal across 32-bit integer, 64-bit integer, double and decimal types, at any nesting depth. A processed write to such a document invalidates the cached entry.
- Values that MongoDB does not consider equal, such as the double `19.99` and the decimal `19.99`, stay distinct.
- Which reads are cacheable does not change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cache-core`: Identity generations match MongoDB numeric equality.

## Impact

- Code: `src/client_query_cache/_core/order_sensitive_keys.py`.
- Tests: core unit and property tests, plus synchronous and asyncio facade integration tests.
- Docs: `docs/development/architecture.md` and `CHANGELOG.md`.
