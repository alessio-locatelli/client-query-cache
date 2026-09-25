# Proposal

## Why

The collection-type check treats MongoDB time-series collections as cacheable even though MongoDB does not support change streams for them. Reads can therefore retain results that later writes cannot invalidate; this must be addressed before completing `document-public-library`.

## What Changes

- Require a confirmed ordinary collection before using the cache in either execution model; time-series collections and views use the existing direct-read path.
- Recheck absent or inconclusive collection metadata on later reads without caching their results, so an absent name later created as a time-series collection cannot retain cached negative results.
- Preserve direct PyMongo options, return shapes, and errors, and keep ordinary collection caching and epoch-based metadata refresh.
- Add regression coverage for every supported read method and collection lifecycle transitions, and update the current README bypass guidance.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cached-read-api`: Restrict cache eligibility to confirmed ordinary collections, including safe handling of absent namespaces and time-series reads.

## Impact

Changes the shared collection metadata model, synchronous and asynchronous manager eligibility checks, associated tests, and a focused README statement. No public signature, dependency, stream count, or cache budget changes are planned. Reads of absent collections become uncached; missing documents in existing ordinary collections remain cacheable.

This is a separate prerequisite change requested by the user. The broader `document-public-library` change remains pending and is not implemented here.
