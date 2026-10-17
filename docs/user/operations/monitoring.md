# Monitoring

Choose diagnostics for the manager you use. Process-local `CacheManager` exposes capacity, detailed bypass reasons and stream health. `SharedCacheManager` exposes only worker-local outcome totals; see [shared diagnostics](#shared-manager-diagnostics).

Measure hit rate alongside request latency, application and MongoDB CPU, and memory. A healthy stream does not mean a writer's latest event has arrived; see [consistency](../usage/consistency.md).

## Observability

The remainder of this section describes synchronous and asyncio **process-local `CacheManager`** instances.

- **Logging**: every component logs through the standard `logging` module under `client_query_cache.*` logger
  names (for example, `client_query_cache.synchronous.streams` logs stream reconnects and shutdown warnings). Attach
  handlers the same way you would for any other library; no separate configuration mechanism exists.
- **Runtime cache statistics**: `cache_manager.snapshot()` returns an immutable snapshot with the manager's
  lifecycle state, resident bytes, configured budget and max entry size, entry count, and cumulative hits, misses,
  evictions, bypasses, and oversized bypasses. `bypass_reasons` contains fixed `BypassReasonCount` records in
  `BypassReason` order, including zeros. Ordinary reasons sum to `bypasses`; oversized recordings are separate.
  Counters describe recording events: a read records at most one hit or miss, and can also record more than one bypass.
  Cache snapshots omit document contents, queries and credentials.
- **Per-database stream telemetry**: `cache_manager.stream_cost_snapshot(database_name)` returns manager iteration-call counts,
  logical event bytes, invalidation counts, and invalidation-delivery-lag samples for one database, and
  `cache_manager.active_stream_cost_databases()` lists which databases currently have telemetry. This is the
  same telemetry the [stream-cost benchmark suite](../benchmarks/stream-cost.md) uses; the lag samples carry an
  explicit clock-skew disclaimer since they compare the MongoDB server's clock to your application host's.
  The `stream_polls` field counts calls to change-stream iteration; one call can issue multiple `getMore` commands.

### OpenTelemetry metrics

Install the `otel` extra (`pip install client-query-cache[otel]`) and call `register_cache_metrics` to bridge the
statistics above into a `Meter` from your application's own OpenTelemetry SDK setup:

```python
from opentelemetry.sdk.metrics import MeterProvider

from client_query_cache.otel import register_cache_metrics

# Configure your application's readers/exporters here.
provider = MeterProvider()
meter = provider.get_meter("your-application")
register_cache_metrics(meter, cache_manager)
```

`client_query_cache.otel` is a separate module from the rest of the package: only importing it requires
`opentelemetry-api`, so the base install has no OpenTelemetry dependency. `register_cache_metrics` only registers
instruments against the `Meter` you pass in — configuring a `MeterProvider`, exporter, and collection interval is
your application's responsibility; see the
[OpenTelemetry Python documentation](https://opentelemetry.io/docs/languages/python/) for that setup.

| Instrument                                                                                       | Type    | Meaning                                                                                                                  |
| ------------------------------------------------------------------------------------------------ | ------- | ------------------------------------------------------------------------------------------------------------------------ |
| `client_query_cache.cache.hits` / `.misses` / `.evictions` / `.bypasses` / `.bypasses.oversized` | counter | cumulative cache outcomes, manager-wide                                                                                  |
| `client_query_cache.cache.entries`                                                               | gauge   | current resident entry count, manager-wide                                                                               |
| `client_query_cache.cache.resident_bytes`                                                        | gauge   | current resident bytes across the shared budget, manager-wide                                                            |
| `client_query_cache.stream.polls` / `.invalidations` / `.logical_event_bytes`                    | counter | cumulative stream activity, tagged per database with `db.namespace`                                                      |
| `client_query_cache.stream.invalidation_lag`                                                     | gauge   | invalidation-delivery-lag percentiles (p50/p95/max by default), tagged per database with `db.namespace` and `percentile` |

Lag gauges summarize retained samples and compare server and application clocks. Clock skew can distort them; they are not an application freshness guarantee. Use the [benchmark methodology](../benchmarks/stream-cost.md) for controlled measurements.

## Bypass reasons and stream health

`manager.snapshot().bypass_reasons` explains ordinary bypass events using this fixed vocabulary:

| Reason                                                  | Meaning                                                                                 |
| ------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| `session`                                               | The read uses a session.                                                                |
| `read_profile`                                          | The collection's read preference or concern is incompatible with caching.               |
| `unsupported_options`                                   | The read supplies options that cannot be cached.                                        |
| `unsafe_filter`, `unsafe_projection`, `unsafe_pipeline` | The request contains a construct unsafe to cache.                                       |
| `uncanonicalizable_key`                                 | The request cannot form a stable cache key.                                             |
| `missing_collection`                                    | The collection does not exist.                                                          |
| `view_collection`, `time_series_collection`             | The collection type does not support caching.                                           |
| `metadata_unavailable`                                  | Collection metadata could not be established.                                           |
| `stream_unavailable`                                    | The database stream is unavailable.                                                     |
| `admission_invalidated`                                 | Stream continuity changed during admission, although the stream is currently available. |
| `unspecified`                                           | An advanced caller recorded a bypass without a reason.                                  |

If several request checks would bypass a read, the first failing check supplies its reason: session, read profile, unsupported options, unsafe filter or pipeline, unsafe projection, then cache-key suitability. These checks precede collection and stream eligibility. A missing collection or unavailable metadata is checked again on later reads. For unexpected bypasses, check the recorded reason first, then the [eligibility contract](../reference/api.md#bypass-conditions).

`manager.stream_health_snapshot(database_name)` reports `not_started`, `connecting`, `healthy`,
`reconnecting`, `startup_failed`, or `closed`. Inspection is synchronous for sync and asyncio `CacheManager` and never
starts a stream. Its `requested_database_name` echoes the name you passed without checking it against MongoDB. While the manager is open, a name without a stream, including an empty or mistyped one, reports `not_started`. `connecting` covers initial startup until it is available to cached reads. An actual
failed attempt emits a startup warning and leaves `startup_failed` visible during its retry cooldown;
reads continue through PyMongo and record `stream_unavailable` without another startup warning.
A later read can initiate a retry and move health through `connecting` to `healthy`. See
[startup retry and recovery](deployment.md#retry-and-error-handling) for timing. `reconnecting` describes
automatic recovery of an established stream. `healthy` reports stream operation; it does not guarantee
that an independent writer's latest change has been processed. Use direct PyMongo reads when freshness
is required, as described in [consistency](../usage/consistency.md).

The separate `client_query_cache.cache.bypasses.by_reason` OpenTelemetry counter uses only
`cache.bypass.reason`. It reports the same ordinary reason counts without query, collection, database,
or error attributes. The aggregate and oversized counters remain separate. Advanced registrations
using `manager.cache_core`, including the `cache_core=` keyword, are supported.

## Shared manager diagnostics

```python
counts = manager.snapshot()  # SharedCacheStatistics; synchronous in both APIs.
print(counts.hits, counts.misses, counts.bypasses)
```

These cumulative totals belong to this worker's manager. They do not aggregate other workers or report owner capacity, entry count, bypass reasons, stream health or invalidation lag. `register_cache_metrics` requires the process-local statistics interface and does not support shared managers. Export the three counters through your application's telemetry if needed, identifying workers and handling restarts as counter resets.

To investigate low reuse, check the [shared query scope](../reference/shared-cache.md#worker-managers-and-reads), owner logs and liveness, worker plus owner memory, and configured capacities. Returning a document alone is not proof of a hit. The [shared web self-check](../examples/fastapi-shared.md) combines worker snapshots with actual MongoDB command counts to verify reuse across processes.

Monitor the parent as well as workers: losing it stops the owner. Temporary owner outages can leave HTTP requests succeeding through direct reads while cache hit rates fall. Persistent access, credential and protocol errors remain visible failures; see [shared recovery](shared-cache.md#consistency-and-recovery).
