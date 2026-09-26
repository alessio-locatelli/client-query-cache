# Design

## Context

See `proposal.md` - Why. The manager already exposes two pull-based snapshot accessors: `CacheCore.snapshot()` -> `CacheSnapshot` (`src/client_query_cache/_core/snapshots.py`) and `CacheCore.stream_cost_snapshot(database)` / `CacheCore.active_stream_cost_databases()` -> `StreamCostSnapshot` (`src/client_query_cache/_core/stream_cost.py`). Neither the manager nor the base package has any listener/event-hook mechanism today (unlike PyMongo's `pymongo.monitoring`); every existing signal is pull-based. `used_bytes` (`CacheSnapshot`) and `resident_bytes` (`StreamCostSnapshot`) are the same manager-wide `_lru.snapshot_usage()` value surfaced under two names (`_core/manager.py:889-891`) - the adapter must not double-report it.

There is no stable OpenTelemetry semantic convention for cache hit/miss metrics as of this writing (only `db.client.connection.*` and `db.client.operation.duration` are defined for database clients); custom instrument names are therefore necessary, not an oversight. PyMongo's own OTel contrib instrumentation (`opentelemetry-instrumentation-pymongo`) emits spans only, no metrics, confirming there is no existing convention to mirror for this project's metrics either. `db.namespace` is the current stable OpenTelemetry attribute key for a database name (superseding `db.name` under `OTEL_SEMCONV_STABILITY_OPT_IN=database`); the adapter hardcodes this string rather than depending on the separate `opentelemetry-semantic-conventions` package, keeping the extra's dependency footprint to `opentelemetry-api` alone.

## Goals / Non-Goals

**Goals:**

- Bridge every existing cache/stream-cost snapshot field (except the `used_bytes`/`resident_bytes` duplicate, collapsed to one gauge) into OpenTelemetry metrics with no hard OpenTelemetry dependency on the base install.
- Keep the adapter stateless and read-only: it holds no counters of its own and never mutates manager state.
- Make per-database dimensioning automatic (no caller-side database enumeration).

**Non-Goals:**

- Tracing spans, OTel log export, or any new push-based listener/event-hook mechanism (see proposal.md - What Changes).
- A true per-event `Histogram` for invalidation lag (would require the push mechanism above).
- Exposing `CacheSnapshot.lifecycle` (a state string, not a numeric metric), or the static `shared_budget_bytes` / `max_entry_bytes` configuration values, as OTel instruments. These aren't measurements of activity and can be added later as a `Gauge`/attribute pair without changing this design if a concrete need shows up.
- A dedicated CI job or test matrix for "with/without the extra installed" - see Migration Plan.

## Decisions

**Module placement and import guard.** Add one new top-level module, `src/client_query_cache/otel.py` (not under `_core/`, since it only reads already-public accessors and has no internal state of its own). It is never imported by `client_query_cache/__init__.py` or any other module, so the base package's importability is structurally guaranteed rather than tested by convention. The module's own first lines wrap `from opentelemetry.metrics import Meter, Observation` (and friends) in a `try/except ImportError`, re-raising with a message naming `opentelemetry-api` and the `client-query-cache[otel]` extra. Alternative considered: a generic internal "optional dependency" helper - rejected as unnecessary abstraction for a single call site (this is the project's first and only optional dependency).

**Single stateless entry point.** `register_cache_metrics(meter: Meter, cache_core: CacheCore, *, lag_percentiles: tuple[float, ...] = (0.5, 0.95, 1.0)) -> None`. It registers one `ObservableCounter`/`ObservableGauge` per instrument via `meter.create_observable_counter(...)`/`meter.create_observable_gauge(...)`, each with a callback closing over `cache_core`. It returns `None` and keeps no handle: OpenTelemetry's `Meter`/`MeterProvider` already owns instrument lifetime, and the adapter has nothing else to track since it is stateless. Alternative considered: returning a handle object with an explicit `close()`/`unregister()` - rejected because it would imply the adapter owns lifecycle state it doesn't actually have; shutdown is already the application's `MeterProvider` responsibility.

**Instrument names and units** (namespaced under `client_query_cache.*`, per OpenTelemetry's general metric-naming guidance of a dot-separated namespace with the unit conveyed by the instrument's `unit` field, not the name):

| Instrument                                      | Type                                                                    | Unit | Source field                                                 | `db.namespace` attribute? |
| ----------------------------------------------- | ----------------------------------------------------------------------- | ---- | ------------------------------------------------------------ | ------------------------- |
| `client_query_cache.cache.hits`                 | ObservableCounter                                                       | `1`  | `CacheSnapshot.hits`                                         | no (manager-wide)         |
| `client_query_cache.cache.misses`               | ObservableCounter                                                       | `1`  | `CacheSnapshot.misses`                                       | no                        |
| `client_query_cache.cache.evictions`            | ObservableCounter                                                       | `1`  | `CacheSnapshot.evictions`                                    | no                        |
| `client_query_cache.cache.bypasses`             | ObservableCounter                                                       | `1`  | `CacheSnapshot.bypasses`                                     | no                        |
| `client_query_cache.cache.bypasses.oversized`   | ObservableCounter                                                       | `1`  | `CacheSnapshot.oversized_bypasses`                           | no                        |
| `client_query_cache.cache.entries`              | ObservableGauge                                                         | `1`  | `CacheSnapshot.entry_count`                                  | no                        |
| `client_query_cache.cache.resident_bytes`       | ObservableGauge                                                         | `By` | `CacheSnapshot.used_bytes` (== stream-cost `resident_bytes`) | no                        |
| `client_query_cache.stream.polls`               | ObservableCounter                                                       | `1`  | `StreamCostSnapshot.stream_polls`                            | yes                       |
| `client_query_cache.stream.invalidations`       | ObservableCounter                                                       | `1`  | `StreamCostSnapshot.invalidations`                           | yes                       |
| `client_query_cache.stream.logical_event_bytes` | ObservableCounter                                                       | `By` | `StreamCostSnapshot.logical_event_bytes`                     | yes                       |
| `client_query_cache.stream.invalidation_lag`    | ObservableGauge (one per configured percentile, attribute `percentile`) | `s`  | derived from `StreamCostSnapshot.invalidation_lag_windows`   | yes                       |

Manager-wide instruments read `cache_core.snapshot()` once per callback invocation. Per-database instruments read `cache_core.active_stream_cost_databases()` then `cache_core.stream_cost_snapshot(db)` for each, emitting one `Observation` per database via the callback's returned iterable - this is exactly the shape OpenTelemetry's observable-callback API expects (a callback may return zero or more observations per invocation), so "new database appears" / "database's telemetry resets to absent" fall out of the existing callback contract for free rather than needing special-cased adapter logic.

**Percentile computation is a simple order-statistic quantile, not `stream-cost-benchmarking`'s block bootstrap.** The benchmark suite's block-bootstrap confidence intervals exist to support pre-registered, report-grade statistical claims (see `stream-cost-observability`'s spec). A live gauge refreshed on every collection interval is a different use case - an operational at-a-glance signal, not a scientific estimate - so a plain nearest-rank order statistic over the flattened, currently retained samples is proportionate. Concretely: sort the flattened samples and, for a requested percentile `p` in `[0, 1]` over `n` samples, take the value at index `round(p * (n - 1))`. This handles both edge cases the naive `statistics.quantiles()` API does not: a single retained sample (`n == 1`) returns that sample for any requested percentile instead of raising `StatisticsError` (which `quantiles()` does below `n == 2`), and `p == 1.0` resolves to index `n - 1`, i.e. the maximum, rather than requiring a distinct "max" code path (`quantiles()` only produces interior cut points, never the 0th/100th). The gauge's description explicitly states it is a simple order-statistic quantile over currently retained samples, not a confidence-interval estimate, so it is never mistaken for one.

**Dependency placement in `pyproject.toml`.** Add `[project.optional-dependencies] otel = ["opentelemetry-api>=1.20"]` (first optional-dependencies section in the project) and separately add `opentelemetry-api` to the existing dev dependency group, so contributors and CI always have it available for tests without it being a runtime requirement of the base install - `development-environment`'s existing requirement that "published runtime dependencies SHALL remain distinct from development tooling" already covers keeping these two declarations separate; this design just follows it for the first time.

## Risks / Trade-offs

- [Risk] A future stable OpenTelemetry semantic convention formalizes cache metrics under different names than `client_query_cache.*`, causing a rename. -> Mitigation: all instrument names/units live in one small table in one module; a future rename is a one-place, additive change (old names can be kept alongside new ones during a transition, the same pattern OTel's own `OTEL_SEMCONV_STABILITY_OPT_IN=*/dup` modes use).
- [Risk] The simple quantile computed from retained lag windows could be misread as carrying the same statistical rigor as the benchmark suite's calibrated confidence intervals. -> Mitigation: the gauge's OpenTelemetry description string states plainly that it's a simple quantile over currently retained samples, and documentation (`docs/architecture.md`) draws the same distinction explicitly.
- [Risk] Adding the project's first optional extra could tempt future contributors to add further extras without mirroring them into the dev dependency group, silently losing test coverage for the extra path. -> Mitigation: this design documents the dev-group-mirrors-extra pattern explicitly so it's a documented precedent for the next optional dependency, not a one-off exception.

## Migration Plan

Purely additive: no existing public API, snapshot field, or on-disk/wire format changes. Nothing to migrate. Rollback is simply not installing the `otel` extra or not calling `register_cache_metrics`; there is no persisted state to unwind. Because `opentelemetry-api` is present in the dev dependency group, the existing `unit` test tier already exercises the adapter on every CI run without a new workflow job; the "importable without the extra" guarantee is verified by a targeted unit test that removes `opentelemetry` from `sys.modules` before importing the adapter module (a standard optional-dependency test technique), not by a separate install matrix.
