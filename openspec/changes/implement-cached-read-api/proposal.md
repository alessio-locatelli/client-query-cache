## Why

Once local storage and coherency exist, applications need a narrow, predictable PyMongo-facing API that uses them without changing unsupported operations or weakening read semantics.

## What Changes

- Add synchronous and asyncio collection facades around caller-owned PyMongo clients.
- Support identity lookups and fully materialized bounded read results with documented cache admission and bypass rules.
- Preserve primary/majority semantics, session bypass, value isolation, and raw-PyMongo fallback.

## Capabilities

### New Capabilities

- `cached-read-api`: Supported synchronous and asynchronous coherent cached reads.

### Modified Capabilities

- None.

## Impact

- Adds public facades and integration tests; it depends on `implement-change-stream-coherency`.
