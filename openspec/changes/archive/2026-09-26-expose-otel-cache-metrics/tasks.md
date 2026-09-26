# Tasks

## 1. Dependency setup

- [x] 1.1 Add the `otel` extra depending on `opentelemetry-api` via `uv add --optional otel opentelemetry-api`, and add `opentelemetry-api` to the dev dependency group via `uv add --dev` (never hand-edit `pyproject.toml`'s version bounds, so the resolved lower bound reflects the actual latest resolvable version, per `development-environment`'s existing dependency-floor requirement); verify `uv lock` regenerates cleanly and `uv sync` installs it into the dev environment.
- [x] 1.2 Verify `uv build` still produces a base wheel that installs and imports in a clean environment without `opentelemetry-api` present (per `development-environment`'s existing isolated-install scenario), confirming the extra adds no transitive requirement to the base install.

## 2. Manager-wide cache metrics

- [x] 2.1 Add `src/client_query_cache/otel.py` with the `opentelemetry.metrics` import wrapped so a missing `opentelemetry-api` raises an actionable error naming the package and the `client-query-cache[otel]` extra; verify with a unit test that simulates the dependency's absence (removing `opentelemetry` from `sys.modules`/`sys.path` before importing the module) and asserts the raised error's message.
- [x] 2.2 Add a unit test asserting `import client_query_cache` (the base package, not the new module) succeeds and every existing public name remains importable when `opentelemetry` is absent from `sys.modules`, verifying the base package never imports the new module.
- [x] 2.3 Implement `register_cache_metrics(meter, cache_core, *, lag_percentiles=(0.5, 0.95, 1.0))` registering the manager-wide `ObservableCounter`s (`client_query_cache.cache.hits`/`.misses`/`.evictions`/`.bypasses`/`.bypasses.oversized`) and `ObservableGauge`s (`client_query_cache.cache.entries`, `client_query_cache.cache.resident_bytes`) from design.md's instrument table, reading only `cache_core.snapshot()`; verify with unit tests using a fake `Meter`/`CacheCore` snapshot that each callback reports the expected value and none carry a `db.namespace` attribute.
- [x] 2.4 Add a unit test verifying that invoking every registered callback any number of times leaves a subsequent `cache_core.snapshot()` call's cumulative fields and capture windows unchanged (no reset/mutation), per `otel-metrics`'s "Metrics collection never mutates cache or stream-cost state" requirement.

## 3. Per-database stream-cost and lag metrics

- [x] 3.1 Implement the per-database `ObservableCounter`s (`client_query_cache.stream.polls`/`.invalidations`/`.logical_event_bytes`) whose callbacks iterate `cache_core.active_stream_cost_databases()` and emit one `Observation` per database carrying the `db.namespace` attribute; verify with a unit test using a fake `CacheCore` exposing two databases that the callback yields exactly one observation per database with the correct attribute and value, and yields none when no databases are active.
- [x] 3.2 Implement the derived invalidation-lag percentile `ObservableGauge`s: for each database returned by `active_stream_cost_databases()`, flatten its currently retained `invalidation_lag_windows`, sort them, and compute each configured percentile `p` as the value at index `round(p * (n - 1))` (design.md's nearest-rank method, which handles a single retained sample and `p == 1.0` without raising or needing a separate max code path), then emit an observation per (database, percentile) carrying `db.namespace`, a `percentile` attribute, and a description stating the clock-skew limitation and that this is a simple order-statistic quantile over currently retained samples, not a confidence-interval estimate; verify with a parametrized unit test covering a database with multiple retained samples (correct percentile values including `p == 1.0`), a database with exactly one retained sample (returns that sample without raising), and a database with none (no observation emitted for it that cycle).
- [x] 3.3 Add a unit test verifying the manager-wide resident-bytes gauge (task 2.3) reports exactly one observation regardless of how many databases have active stream-cost telemetry, confirming it is not duplicated per database.
- [x] 3.4 Validate `lag_percentiles` in `register_cache_metrics` before registering any instrument, rejecting a non-finite value or one outside `[0.0, 1.0]` with `CacheConfigurationError`, so an invalid caller-supplied percentile fails at registration instead of raising from `_percentile` during a later metrics collection cycle; verify with a parametrized unit test covering a negative value, a value above 1.0, NaN, and infinity.

## 4. Documentation

- [x] 4.1 Add an OpenTelemetry subsection to `docs/architecture.md`'s Observability section documenting the `otel` extra, `register_cache_metrics`, the instrument-to-snapshot-field mapping, and the simple-quantile-vs-benchmark-confidence-interval distinction for the lag gauges; verify the documented usage snippet runs against a real `MeterProvider` in a doctest or example test.
- [x] 4.2 Add a short README mention pointing to the new architecture.md subsection, consistent with `public-library-documentation`'s existing requirement that the README link deeper observability guidance rather than duplicate it; verify the link target exists.

## 5. Code Quality

- [x] 5.1 Scan every test added or edited in this change (tasks 1-4) and confirm AGENTS.md's "Writing Tests" guidelines are applied, including `@pytest.mark.parametrize` for the percentile and multi-database cases in tasks 3.1-3.2.
- [x] 5.2 Confirm no new prose/comments were added to `src/client_query_cache/otel.py` or any other edited source file; any "why" explanation belongs in this change's specs or the commit body instead.
