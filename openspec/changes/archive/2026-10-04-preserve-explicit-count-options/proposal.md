# Proposal

## Why

[Issue #151](https://github.com/alessio-locatelli/client-query-cache/issues/151) reports that cached counts discard explicitly supplied falsy bounds, masking native errors. Both execution models must preserve native option presence and normalize only equivalent cache shapes.

## What Changes

- Preserve explicit native count options, including `hint=None`, while sharing keys for equivalent zero skip.
- Cover native errors with cold, warm, and bypassed reads in both facades.
- Document count option behavior.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cached-read-api`: Preserve explicit count bounds and native validation.

## Impact

Synchronous and asyncio collection facades, shared count normalization, collection regressions, and cached-read documentation. No dependency changes.
