## Why

Cached values are useful only while the library can invalidate them safely after MongoDB changes. Change-stream ownership, recovery, and uncertainty handling are a distinct correctness boundary from local storage.

## What Changes

- Add one database-scoped change-stream manager and event dispatcher.
- Add event-driven invalidation, resumable reconnects, and clear-on-uncertainty behavior.
- Add minimal event projection that preserves invalidation and resume fields while avoiding unneeded documents.

## Capabilities

### New Capabilities

- `change-stream-coherency`: Database-scoped cache invalidation and safe recovery from stream interruptions.

### Modified Capabilities

- None.

## Impact

- Adds sync and asyncio stream workers and replica-set tests; it depends on `implement-cache-core`.
