# Proposal

## Why

The real-library examples inspect `manager.cache_core.snapshot()`, but an adopter cannot explain the reported bypasses or inspect a database's stream health through the manager. A professional public diagnostics interface should answer whether caching works and why it does not, without exposing cache internals or application data.

## What Changes

- Add synchronous, read-only `snapshot()`, `stream_health_snapshot(database_name)`, `stream_cost_snapshot(database_name)`, and `active_stream_cost_databases()` accessors to both manager variants, with publicly importable immutable snapshot types.
- Classify existing bypass accounting with a fixed public reason enumeration; preserve aggregate counters, oversized accounting, and the current event-counting semantics.
- Preserve the documented `cache_core` API for advanced use. Let the optional OpenTelemetry bridge accept either a manager or its existing cache-core argument through a shared typed statistics interface.
- Extend OpenTelemetry with reason-labelled bypass observations while retaining the aggregate instrument and optional dependency boundary.
- Share eligibility classification between execution models and retain enough collection-probe and stream state to explain missing collections, unsupported collection types, metadata failures, and unhealthy streams.
- Update current public examples and guidance to use manager diagnostics.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cache-core`: manager-level immutable inspection and fixed bypass-reason accounting.
- `change-stream-coherency`: read-only per-database health inspection, including unsuccessful startup.
- `otel-metrics`: manager-compatible statistics sources and a bounded bypass-reason metric dimension.

## Impact

Touches the shared snapshot/statistics and collection-metadata modules, both managers, collections and stream coordinators, public exports, `otel.py`, diagnostics tests, and public usage documentation/examples. It adds no base dependency and no MongoDB request to inspection or a healthy cache hit. Existing totals remain cumulative observations rather than a partition of application requests. The adapter evaluation and causal barrier are independent changes; this change does not expose resume positions or claim stream health proves write catch-up.
