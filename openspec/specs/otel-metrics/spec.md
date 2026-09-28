# otel-metrics Specification

## Purpose

This capability bridges the manager's existing cache and stream-cost snapshot statistics into OpenTelemetry metrics through an optional, import-guarded adapter, without adding OpenTelemetry as a dependency of the base package.

## Requirements

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

### Requirement: Cumulative counts are observable counters

The adapter SHALL expose hits, misses, evictions, bypasses, oversized bypasses, stream polls, invalidations, and logical event bytes as OpenTelemetry `ObservableCounter` instruments equal to current snapshot totals.

#### Scenario: A metrics collection cycle reads current cumulative counts

- **WHEN** an OpenTelemetry metrics collection cycle invokes the registered counters' callbacks
- **THEN** each counter reports the current cumulative value of its corresponding cache or stream-cost snapshot field

### Requirement: Point-in-time cache state is exposed as observable gauges

The adapter SHALL register an OpenTelemetry `ObservableGauge` for entry count and one for the manager's shared resident-byte usage. Each gauge's reported value SHALL equal the corresponding snapshot field's current value at collection time, and SHALL NOT be treated as a monotonic or cumulative quantity.

#### Scenario: Resident bytes decreases between collection cycles

- **WHEN** cache evictions or a namespace clear reduce the manager's resident bytes between two metrics collection cycles
- **THEN** the reported gauge value decreases accordingly, without the adapter or the underlying instrument rejecting or clamping the decrease

### Requirement: Resident bytes has one manager-wide gauge

The adapter SHALL report resident cache bytes once as a manager-wide gauge without a `db.namespace` attribute.

#### Scenario: Resident bytes is not duplicated per database

- **WHEN** the manager has stream-cost telemetry active for more than one database
- **THEN** the resident-bytes gauge reports one manager-wide observation, not one observation per active database

### Requirement: Stream-cost observations discover active databases

At each collection cycle, the adapter SHALL discover active stream-cost databases and label per-database observations with `db.namespace`.

#### Scenario: A new database begins reporting stream-cost telemetry

- **WHEN** a database that previously had no stream-cost telemetry begins having its change stream tracked
- **THEN** subsequent collection cycles include that database's observations, each carrying its database name under the `db.namespace` attribute, without any reconfiguration of the adapter

#### Scenario: A database's stream-cost telemetry is reset

- **WHEN** a database's stream-cost statistics are reset and no telemetry currently exists for it
- **THEN** the adapter's collection callbacks omit observations for that database rather than reporting a stale or fabricated zero value tied to it

### Requirement: Invalidation-delivery lag is exposed as derived percentile gauges

The adapter SHALL expose the invalidation-delivery-lag distribution as one or more `ObservableGauge` instruments computed, at each collection cycle, from the manager's currently retained lag capture windows for each database — never as a synchronous per-event `Histogram`, since OpenTelemetry defines no observable or asynchronous Histogram instrument.

#### Scenario: A percentile gauge is computed from retained capture windows

- **WHEN** a metrics collection cycle runs while a database has retained invalidation-lag capture windows
- **THEN** the adapter computes the configured percentile(s) from the currently retained windows and reports them as gauge values

### Requirement: Percentile gauges carry the clock-skew limitation

Each reported percentile gauge's description or attributes SHALL carry the same clock-skew limitation already defined for the underlying raw lag distribution, so a consumer of the metric sees the same caveat the manager's own snapshot carries.

#### Scenario: A percentile gauge's description states the clock-skew limitation

- **WHEN** a metrics collection cycle reports a percentile gauge value
- **THEN** its description carries the same clock-skew limitation label as the manager's raw invalidation-lag snapshot

### Requirement: A percentile gauge without retained samples is omitted, not fabricated

When a database has no retained lag samples at collection time, the adapter SHALL omit that database's percentile observations for that cycle rather than report a fabricated or default value.

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

### Requirement: An invalid configured lag percentile is rejected at registration

The adapter SHALL validate every caller-supplied lag percentile before registering any instrument. A percentile that is not a finite number in the range `[0.0, 1.0]` SHALL cause registration to fail immediately, rather than registering successfully and failing later during a metrics collection cycle.

#### Scenario: A percentile outside the valid range is rejected

- **WHEN** a caller supplies a lag percentile that is negative, greater than `1.0`, `NaN`, or infinite
- **THEN** registration fails immediately with an actionable configuration error, and no instrument is registered
