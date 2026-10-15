# Reduce shared-cache miss cost

## Why

[Issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272) records failed cold-miss bounds in the version 5 study. Its successful local hit path still sends each miss through the Python owner before reading MongoDB.

## What Changes

- Capture admission validity from the read-only shared index before a native read, removing the synchronous miss selection request when published metadata is usable.
- Hand off encoded local admissions through a bounded native session queue, reducing worker socket sends and batching owner wakeups.
- Evaluate the candidate under a fresh registration, including the existing timed fault driver.

## Capabilities

### Modified Capabilities

- `shared-cache-benchmarking`: Fence locally captured misses and retain complete follow-up evidence.

## Impact

The native extension, shared-cache adapters and owner, core locking and observer notification, and research reports change. The supported cache API and sorted-find path remain unchanged.
