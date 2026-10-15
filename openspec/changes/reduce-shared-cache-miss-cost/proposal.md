# Reduce shared-cache miss cost

## Why

[Issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272) requires bounded cold-miss latency alongside the existing hot, active, capacity and fault gates. Local capture and native admission queues are implemented, but the registered studies still fail required cold P99 bounds. Admission costs and the benchmark relay's TCP policy need further work before the issue can close.

## What Changes

- Capture admission validity from the read-only shared index before a native read, removing the synchronous miss selection request when published metadata is usable.
- Hand off encoded local admissions through a bounded native session queue, reducing worker socket sends and batching owner wakeups.
- Reduce measured guard, copying, scalar normalization and owner polling costs while preserving admission authority.
- Match the byte-counting relay's TCP delivery policy to the driver and qualify the changed observer afresh.
- Evaluate the candidate under a fresh registration, including the existing timed fault driver.

## Capabilities

### Modified Capabilities

- `shared-cache-benchmarking`: Fence locally captured misses and retain complete follow-up evidence.
- `stream-cost-benchmarking`: Preserve the driver's TCP delivery policy through byte-counting relays.
- `development-environment`: Exclude named public integrity digests from secret findings without repeated baseline entries.

## Impact

The native extension, shared-cache adapters and owner, core scalar paths and locking, benchmark relays, secret-scanner baseline and research reports change. The supported cache API and sorted-find path remain unchanged.
