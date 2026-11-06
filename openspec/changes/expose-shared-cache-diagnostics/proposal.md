# Proposal

## Why

An operator whose shared-cache hit rate is low cannot tell from the public API why: `SharedCacheManager.snapshot()` reports only three worker-local totals. Reads that bypass because a database is missing from the server configuration, a collection uses an unsupported collation, the owner is unreachable, its stream failed to start or its namespace capacity is exhausted all look identical. Owner-wide capacity, per-database stream status and owner restarts are visible only through a private wire message that tests and benchmarks use. Issue #336 asks for a supported interface.

## What Changes

- `snapshot()` on both shared managers gains bounded bypass reasons and a separate oversized count. Shared `bypasses` stops including oversized results, matching the process-local contract.
- New `owner_snapshot()` (synchronous call, or `await` with asyncio) asks the owner for capacity use of four configurable limits, cumulative evictions and rejected connections, owner incarnation and uptime, and one stream status per configured database. It returns `None` when the owner does not answer, never a zero-valued snapshot.
- `register_cache_metrics` accepts shared managers and exports their worker-local counters only.
- The shared FastAPI example gains a diagnostics route verified by its self-check. The monitoring guide gains symptom-to-cause interpretation, including owner interruption and restart. The API reference, `context7.json` and the changelog are updated.
- Owner-scope OpenTelemetry metrics are not part of this change; they are tracked in #424.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `shared-worker-cache`: worker and owner diagnostics, their scopes and failure behavior.
- `otel-metrics`: worker-scope metrics for shared managers.

## Impact

Touches `_shared/adapters.py`, `_shared/coordinator.py`, a new `_shared/diagnostics.py`, `otel.py`, the public exports of `client_query_cache`, its `synchronous` and `asynchronous` packages, `tests/shared_cache`, `tests/test_otel.py`, `examples/fastapi_shared_example.py`, the monitoring and shared-cache guides, `context7.json` and `CHANGELOG.md`. Adds no dependency, no cache-hit work and no background activity. The owner wire message `observe` is extended additively.
