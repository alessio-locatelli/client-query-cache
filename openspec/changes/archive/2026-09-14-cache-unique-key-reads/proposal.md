## Why

`implement-cached-read-api` caches only `_id` as a document identity; every other equality read (e.g. by a unique `email` field) falls back to the lower-hit-rate generic namespace-guarded path. Closing that gap safely requires knowing which fields the database actually enforces as unique, which is substantial enough — index discovery, exclusion of indexes whose uniqueness guarantee is conditional, collation matching, alias resolution and re-verification — to warrant its own change rather than being folded into the facade foundation.

## What Changes

- Discover unique keys automatically from server-side index metadata (`list_indexes()`) rather than requiring a caller declaration, re-verified whenever a namespace's epoch advances.
- Cache reads by a discovered unique key as identity-guarded, alias-based entries, reusing cache-core's existing alias mechanism.
- Re-verify a resolved alias against its original predicate on a cache miss, so a write that moves a document off its key, or a drop/recreate that reuses an identity, cannot leak a stale document under a stale alias.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `cached-read-api`: Add unique-key discovery and alias-based identity caching to the existing synchronous and asynchronous cached-read facades.
- `change-stream-coherency`: Route `createIndexes`/`dropIndexes` events, which the stream's operation-type filter currently excludes, so unique-key discovery can react to a live index change.

## Impact

- Extends `synchronous`/`asynchronous` collection facades and their metadata-cache component; depends on `implement-cached-read-api` being archived first.
- Extends `_core/stream_events.py`'s change-stream operation-type filter and routing to include `createIndexes`/`dropIndexes`, which the current filter excludes.
