# Proposal

## Why

`cache-core` and `stream-cost-observability` already track cache hits/misses/evictions/bypasses, stream polls, invalidations, logical event bytes, resident bytes, and invalidation-delivery lag, and `docs/architecture.md` already calls these snapshots "safe to export to a metrics system directly." Today the only way to get them into an application's observability stack is to poll `manager.cache_core.snapshot()` / `stream_cost_snapshot()` and wire the fields into a metrics system by hand. Applications standardizing on OpenTelemetry have to write that bridge themselves, field by field, with no guidance on instrument types, units, or attribute naming. Neither PyMongo nor redis-py embeds OpenTelemetry in its core dependency tree; each instead exposes its own hook/snapshot surface and leaves the OTel bridge to an add-on. This change follows the same shape: it ships that bridge as an optional, import-guarded adapter instead of requiring every consumer to reinvent it.

## What Changes

- Add a new optional extra (`client-query-cache[otel]`) depending only on `opentelemetry-api` (never `-sdk` — the application owns SDK and exporter configuration). The base install gains no new runtime dependency.
- Add a new, import-guarded adapter module that registers OpenTelemetry observable instruments backed by the existing `CacheSnapshot` and `StreamCostSnapshot` accessors: `ObservableCounter` for the monotonic fields (hits, misses, evictions, bypasses, oversized bypasses, stream polls, invalidations, logical event bytes) and `ObservableGauge` for the point-in-time fields (entry count, used bytes, resident bytes).
- Expose invalidation-delivery lag as derived percentile `ObservableGauge`s (e.g. p50/p95/max) computed from the retained capture windows at collection time, since OpenTelemetry has no observable/asynchronous Histogram instrument and recording the raw distribution as a true Histogram would require synchronous per-event instrumentation that is out of scope for this change.
- The adapter accepts a caller-supplied `Meter` and never constructs its own `MeterProvider`, matching how OpenTelemetry instrumentation libraries avoid owning global SDK state.
- Per-database stream metrics are dimensioned using OpenTelemetry's own stable `db.namespace` attribute rather than a project-specific attribute name, so cache metrics correlate with any existing MongoDB OTel data on the same dimension.
- Document the adapter's usage and instrument mapping in `docs/architecture.md`'s Observability section and in the README.
- Explicitly out of scope: tracing spans around cache lookup/admission/invalidation, OpenTelemetry log/event export, and any new push-based listener or event-hook mechanism (a true per-event lag Histogram would need one) — these are candidates for future, separate changes.

## Capabilities

### New Capabilities

- `otel-metrics`: an optional adapter that bridges the existing cache and stream-cost snapshot statistics into OpenTelemetry metrics via caller-supplied instruments, without adding a hard OpenTelemetry dependency to the base package.

### Modified Capabilities

(none — `cache-core` and `stream-cost-observability` already expose the snapshot data this change consumes; their requirements are unchanged.)

## Impact

- `pyproject.toml`: new `[project.optional-dependencies]` section (first one in the project) adding an `otel` extra; `opentelemetry-api` also added to the dev dependency group so it's present for local/CI test runs without being a runtime requirement of the base install.
- New source module under `src/client_query_cache/` for the adapter (import-guarded so `import client_query_cache` never requires `opentelemetry-api`).
- `docs/architecture.md`, `README.md`: new Observability documentation and a usage example.
- New tests: instrument registration and value correctness against `CacheCore`/`StreamCostSnapshot` fixtures, and a test that importing the base package does not require `opentelemetry-api`.
- No change to `_core/manager.py`, `_core/stream_cost.py`, or `_core/snapshots.py` internals — the adapter only reads their existing public accessors.
