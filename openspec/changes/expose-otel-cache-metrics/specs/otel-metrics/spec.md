# Spec Delta

## Purpose

This capability bridges the manager's existing cache and stream-cost snapshot statistics into OpenTelemetry metrics through an optional, import-guarded adapter, without adding OpenTelemetry as a dependency of the base package.

## ADDED Requirements

### Requirement: The adapter is optional and import-guarded

The base package SHALL remain importable and fully functional without `opentelemetry-api` installed. Only importing the OpenTelemetry adapter module itself SHALL require `opentelemetry-api`, and it SHALL fail with an actionable error identifying the missing dependency and the extra that provides it when that dependency is absent.

#### Scenario: The base package is imported without OpenTelemetry installed

- **WHEN** `opentelemetry-api` is not installed and an application imports `client_query_cache`
- **THEN** the import succeeds and every existing feature remains available

#### Scenario: The adapter is imported without OpenTelemetry installed

- **WHEN** `opentelemetry-api` is not installed and an application imports the OpenTelemetry adapter module
- **THEN** the import fails with an error naming `opentelemetry-api` and the extra that installs it, rather than an unguided `ImportError` or `ModuleNotFoundError`

### Requirement: The adapter registers instruments against a caller-supplied Meter

The adapter SHALL accept a caller-supplied OpenTelemetry `Meter` and SHALL register every instrument it exposes against that `Meter`. It SHALL NOT construct or configure its own `MeterProvider`, `Meter`, exporter, or reader, so the application retains sole ownership of OpenTelemetry SDK configuration.

#### Scenario: An application supplies its own configured Meter

- **WHEN** an application constructs its own `MeterProvider` and passes one of its `Meter`s to the adapter
- **THEN** the adapter registers its instruments against that `Meter` and does not create or replace any global OpenTelemetry provider

### Requirement: Cumulative cache and stream-cost counts are exposed as observable counters

The adapter SHALL register an OpenTelemetry `ObservableCounter` for each cumulative, monotonically increasing statistic already exposed by the manager's cache snapshot and stream-cost snapshot: cache hits, misses, evictions, bypasses, oversized bypasses, stream polls, invalidations, and logical event bytes. Each counter's reported value SHALL equal the corresponding snapshot field's current cumulative total at collection time.

#### Scenario: A metrics collection cycle reads current cumulative counts

- **WHEN** an OpenTelemetry metrics collection cycle invokes the registered counters' callbacks
- **THEN** each counter reports the current cumulative value of its corresponding cache or stream-cost snapshot field

### Requirement: Point-in-time cache state is exposed as observable gauges

The adapter SHALL register an OpenTelemetry `ObservableGauge` for entry count and one for the manager's shared resident-byte usage. The cache snapshot's `used_bytes` and each database's stream-cost snapshot `resident_bytes` are the same underlying manager-wide measurement exposed twice today under different names; the adapter SHALL report this measurement as a single gauge, not duplicate it per database or per source field, and that gauge SHALL NOT carry a `db.namespace` attribute, consistent with it being scoped to the manager's shared budget rather than to any one namespace, collection, or stream. Each gauge's reported value SHALL equal the corresponding snapshot field's current value at collection time, and SHALL NOT be treated as a monotonic or cumulative quantity.

#### Scenario: Resident bytes decreases between collection cycles

- **WHEN** cache evictions or a namespace clear reduce the manager's resident bytes between two metrics collection cycles
- **THEN** the reported gauge value decreases accordingly, without the adapter or the underlying instrument rejecting or clamping the decrease

#### Scenario: Resident bytes is not duplicated per database

- **WHEN** the manager has stream-cost telemetry active for more than one database
- **THEN** the resident-bytes gauge reports one manager-wide observation, not one observation per active database

### Requirement: Per-database stream-cost metrics are dimensioned by database without prior enumeration

The adapter SHALL discover which databases currently have stream-cost telemetry at each collection cycle, using the manager's existing accessor for active stream-cost databases, rather than requiring the caller to declare database names in advance. Each per-database counter or gauge observation SHALL carry the observed database name as an attribute using OpenTelemetry's `db.namespace` semantic-convention attribute key.

#### Scenario: A new database begins reporting stream-cost telemetry

- **WHEN** a database that previously had no stream-cost telemetry begins having its change stream tracked
- **THEN** subsequent collection cycles include that database's observations, each carrying its database name under the `db.namespace` attribute, without any reconfiguration of the adapter

#### Scenario: A database's stream-cost telemetry is reset

- **WHEN** a database's stream-cost statistics are reset and no telemetry currently exists for it
- **THEN** the adapter's collection callbacks omit observations for that database rather than reporting a stale or fabricated zero value tied to it

### Requirement: Invalidation-delivery lag is exposed as derived percentile gauges

The adapter SHALL expose the invalidation-delivery-lag distribution as one or more `ObservableGauge` instruments computed, at each collection cycle, from the manager's currently retained lag capture windows for each database — never as a synchronous per-event `Histogram`, since OpenTelemetry defines no observable or asynchronous Histogram instrument. Each reported percentile gauge's description or attributes SHALL carry the same clock-skew limitation already defined for the underlying raw lag distribution, so a consumer of the metric sees the same caveat the manager's own snapshot carries. When a database has no retained lag samples at collection time, the adapter SHALL omit that database's percentile observations for that cycle rather than report a fabricated or default value.

#### Scenario: A percentile gauge is computed from retained capture windows

- **WHEN** a metrics collection cycle runs while a database has retained invalidation-lag capture windows
- **THEN** the adapter computes the configured percentile(s) from the currently retained windows and reports them as gauge values carrying the clock-skew limitation

#### Scenario: A database has no retained lag samples yet

- **WHEN** a metrics collection cycle runs for a database that has recorded no invalidations yet
- **THEN** the adapter reports no percentile-gauge observation for that database in that cycle

### Requirement: Metrics collection never mutates cache or stream-cost state

Registering or invoking the adapter's instrument callbacks SHALL be read-only with respect to the manager's cache and stream-cost statistics: it SHALL NOT reset, clear, or otherwise alter any counter, gauge source, or capture window it reads.

#### Scenario: Repeated metrics collection does not reset counters

- **WHEN** an OpenTelemetry metrics collection cycle runs any number of times
- **THEN** the manager's own `cache_core.snapshot()` and `stream_cost_snapshot()` results are unaffected by that collection, including their cumulative counters and retained capture windows

### Requirement: Exposed metrics carry no application data

Every value, attribute, and description the adapter emits SHALL be limited to the same safe scope already guaranteed by the manager's cache and stream-cost snapshots: no cached document content, query filter, credential, or resume token SHALL appear in any instrument's value, attribute, or description.

#### Scenario: An application exports adapter-registered metrics

- **WHEN** an application's OpenTelemetry pipeline exports the metrics this adapter registers
- **THEN** the exported output contains no cached document, query, or credential value
