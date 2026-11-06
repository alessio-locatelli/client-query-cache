# Monitoring

Choose diagnostics for the manager you use. Process-local `CacheManager` exposes capacity, detailed bypass reasons and stream health. `SharedCacheManager` separates worker-local statistics from an on-demand owner snapshot; see [shared diagnostics](#shared-manager-diagnostics).

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

A shared manager reports two scopes that differ in lifetime, collection time and failure mode:

```python
# Local and synchronous in both APIs: returns SharedCacheStatistics.
statistics = manager.snapshot()
# One owner request: returns SharedOwnerSnapshot or None.
owner = manager.owner_snapshot()
# With the asyncio manager: owner = await manager.owner_snapshot()
```

`snapshot()` reads this worker's counters and never contacts the owner. `owner_snapshot()` sends one request to the owner each time you call it and nothing else polls the owner. Call it from a health or debug endpoint, not on every read. A synchronous call blocks its thread for at most the owner request deadline of 250 ms plus one connection attempt; the asyncio call blocks nothing. A closed manager raises `CacheClosedError`.

### Worker statistics

`SharedCacheStatistics` holds cumulative `hits`, `misses`, ordinary `bypasses` and `oversized_bypasses` for this manager only. Workers are not aggregated, and a restarted worker starts from zero. `bypass_reasons` lists every `SharedBypassReason` once, in enum order and including zeros; the counts sum to `bypasses`. Oversized results are counted separately, as with the process-local manager. The reasons also used by process-local managers keep the meanings in the [table above](#bypass-reasons-and-stream-health). The rest are specific to shared managers:

| Reason                    | Meaning                                                                                                                                                |
| ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `unportable_key`          | The request cannot be encoded as a key shared between workers; see the [shared read contract](../reference/shared-cache.md#worker-managers-and-reads). |
| `shared_scope`            | The read or the collection uses a non-simple collation, which shared caching does not support.                                                         |
| `database_not_authorized` | The database is not in the server's `databases`. Add it, or expect these reads to bypass.                                                              |
| `stream_starting`         | The owner has not yet started the database's stream, or startup failed. Check that database's [owner status](#owner-snapshot).                         |
| `stream_unavailable`      | The owner's stream for the database is not available, for example while reconnecting.                                                                  |
| `progress_expired`        | The stream made no upstream progress for three seconds, so hits are disabled until it does.                                                            |
| `namespace_capacity`      | Every `namespaces` slot is taken. Raise `namespaces` or reduce collection churn.                                                                       |
| `metadata_refresh`        | The worker's collection metadata was stale and refreshed. Occasional occurrences are normal, for example after a collection change.                    |
| `owner_unavailable`       | The owner did not answer: an outage, a restart, a retry cooldown or an exhausted connection limit.                                                     |

### Owner snapshot

`owner_snapshot()` returns `None` when the owner does not answer within its deadline. This covers a stopped or restarting owner, the short retry cooldown after a failed request and an exhausted connection limit. It never returns zeros in place of an answer, so treat `None` as "no answer from this attempt" and ask again. A returned `SharedOwnerSnapshot` describes the owner at the moment it answered:

- `incarnation` is an opaque integer that identifies one owner process. Compare it for equality only. `uptime_seconds` is the owner's age. A restarted owner has a new incarnation, a small uptime, an empty cache and counters that start from zero, so an empty snapshot after a restart is a fresh cache, not a healthy idle one.
- `cache_bytes`, `index_entries`, `namespaces` and `connections` are `SharedCapacityUsage(in_use, limit)` pairs. Their limits are `budget_bytes`, `slots`, `namespaces` and `connections` from [`SharedCacheConfig`](../reference/shared-cache.md#configuration). `evictions` and `rejected_connections` count events since the owner started.
- `streams` has one `SharedDatabaseHealth` per configured database with a `SharedStreamStatus`.

| Stream status      | Meaning                                                                              | Worker reads count             |
| ------------------ | ------------------------------------------------------------------------------------ | ------------------------------ |
| `not_started`      | No read has touched the database since the owner started.                            | `stream_starting` on first use |
| `starting`         | The stream is being opened.                                                          | `stream_starting`              |
| `startup_failed`   | The last attempt failed. Check owner logs and MongoDB access; the next read retries. | `stream_starting`              |
| `unavailable`      | The stream was established and is currently broken or reconnecting.                  | `stream_unavailable`           |
| `progress_expired` | The stream is available but made no upstream progress within three seconds.          | `progress_expired`             |
| `healthy`          | The stream is available and recently made progress.                                  | hits are possible              |

`healthy` reports stream operation. It does not guarantee that an independent writer's latest change has been processed; see [consistency](../usage/consistency.md).

### Interpreting the diagnostics

| Observation                                                                                                      | Likely cause and action                                                                                                                                          |
| ---------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Rising `session`, `unsupported_options`, `shared_scope` or `unportable_key`                                      | The application's reads are ineligible. Change the reads, not the cache; see the [shared read contract](../reference/shared-cache.md#worker-managers-and-reads). |
| Rising `database_not_authorized`                                                                                 | A database is missing from the server's `databases`.                                                                                                             |
| Rising `namespace_capacity`; `namespaces` at its limit                                                           | Raise `namespaces`.                                                                                                                                              |
| Rising `owner_unavailable`; `owner_snapshot()` is `None` for every worker                                        | The owner is down or restarting. Check the parent process and owner logs; see [recovery](shared-cache.md#consistency-and-recovery).                              |
| Rising `owner_unavailable`; a snapshot answers with `connections` at its limit and `rejected_connections` rising | Raise `connections` or reduce connections per worker.                                                                                                            |
| Hit rate dropped and `incarnation` changed or `uptime_seconds` is small                                          | The owner restarted and its cache is warming again. Counters from before the restart are gone.                                                                   |
| `evictions` rising with `cache_bytes` near its limit                                                             | The budget is too small for the working set. Raise `budget_bytes`, or lower per-entry size.                                                                      |
| `index_entries` near its limit while `cache_bytes` has headroom                                                  | The index is full. Raise `slots`.                                                                                                                                |
| Rising `stream_starting` with `startup_failed`                                                                   | The owner cannot open the stream. Check MongoDB reachability and permissions.                                                                                    |
| Rising `progress_expired` with `progress_expired` status                                                         | The owner's stream stalled. Check owner load and MongoDB health.                                                                                                 |

A worker-health endpoint can combine both scopes:

```python
def shared_cache_health(manager):
    statistics = manager.snapshot()
    owner = manager.owner_snapshot()
    if owner is None:
        return {"owner": "no answer", "bypasses": statistics.bypasses}
    return {
        "owner": str(owner.incarnation),
        "uptime_seconds": owner.uptime_seconds,
        "streams": {s.database_name: s.status.value for s in owner.streams},
        "cache_bytes": [owner.cache_bytes.in_use, owner.cache_bytes.limit],
    }
```

The [shared web self-check](../examples/fastapi-shared.md) serves these diagnostics from real workers and combines worker snapshots with actual MongoDB command counts to verify reuse across processes.

### Telemetry

`register_cache_metrics(meter, manager)` accepts shared managers and exports only the worker's `hits`, `misses`, ordinary bypasses, oversized bypasses and per-reason bypasses under the [instrument names above](#opentelemetry-metrics), using the `SharedBypassReason` values for `cache.bypass.reason`. Values are cumulative for one worker, so give each worker's telemetry its own resource identity and treat a restart as a counter reset. Capacity, entry, resident-byte and stream instruments are not registered for shared managers, and collection never contacts the owner. Owner-scope metrics are tracked in [#424](https://github.com/alessio-locatelli/client-query-cache/issues/424).

To investigate low reuse, work through the reasons first, then the [shared query scope](../reference/shared-cache.md#worker-managers-and-reads), owner logs and liveness, worker plus owner memory, and configured capacities. Returning a document alone is not proof of a hit.

Monitor the parent as well as workers: losing it stops the owner. Temporary owner outages can leave HTTP requests succeeding through direct reads while cache hit rates fall. Persistent access, credential and protocol errors remain visible failures; see [shared recovery](shared-cache.md#consistency-and-recovery).
