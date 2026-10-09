# Proposal

## Why

The first eligible `find_one()` in a namespace whose unique-key metadata is not yet known records two misses when its filter matches a unique index ([issue #213](https://github.com/alessio-locatelli/client-query-cache/issues/213)). Manager snapshots and the OpenTelemetry miss counter therefore overstate misses after every manager start and after every index change, which lowers hit ratios that operators compute from them.

## What Changes

- A single eligible `find_one()` records at most one hit or miss in both execution models, including reads that discover unique-key metadata.
- The monitoring guide states the one-outcome rule and drops the known-issue note for issue #213.
- The FastAPI catalogue self-check requires exactly one miss for a cold read instead of accepting any positive miss count.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cached-read-api`: adds a requirement that a single-document read records one cache outcome even when it discovers unique-key metadata.

## Impact

- `CacheCore` namespace lookup and the synchronous and asyncio `CachedCollection.find_one()`.
- `docs/user/operations/monitoring.md`, `examples/fastapi_catalogue_example.py`, `CHANGELOG.md`.
- No public API, dependency, or configuration change.
