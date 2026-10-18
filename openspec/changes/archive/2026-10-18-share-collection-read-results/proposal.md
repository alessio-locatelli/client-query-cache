# Proposal

## Why

Repeated collection reads in different workers cannot currently share results except for exact identity lookups. Deliver the public read coverage requested in [issue #295](https://github.com/alessio-locatelli/client-query-cache/issues/295).

## What Changes

- Extend the shared managers to cache deterministic collection reads with the process-local API as their baseline.
- Establish cursor, invalidation and recovery behavior through separate-process tests and bounded measurements.

## Capabilities

### Modified Capabilities

- `shared-worker-cache`: Public read coverage and shared cursor lifecycle.

## Impact

Shared adapters, owner selection protocol, public documentation, examples, Context7 and existing benchmark harnesses. No new dependencies or constructor changes.
