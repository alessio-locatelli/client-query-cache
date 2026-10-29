# Deployment

This page covers `CacheManager`. For one cache shared by workers, follow [shared deployment](shared-cache.md). Start with [manager selection](../getting-started/choose-a-manager.md) if you are choosing between them.

Create a long-lived PyMongo client and manager inside each worker and reuse them across requests. The manager owns cached data and streams; your application owns the client's credentials, TLS, pools and timeouts. Close the manager before the client, using `with` or `async with`. Never inherit a client or manager from a pre-fork parent.

Use direct reads where freshness is required; [invalidation is asynchronous](../usage/consistency.md). The [catalogue rollout example](../examples/fastapi.md#feature-flagged-rollout) selects direct or cached content reads at application startup and demonstrates rollback.

## Retry and error handling

Initial reads start one stream per database. Concurrent reads for the same database bypass while startup is pending; other databases operate independently. Failed startup logs a warning and subsequent reads retry after a jittered exponential cooldown, starting near 100 ms and capped at 30 seconds. Idle databases do not retry startup in the background. Correcting permissions or topology can therefore restore caching on later reads without replacing the manager.

Established streams reconnect automatically with capped backoff. Reads and admissions bypass during reconnection. If MongoDB can no longer resume from the saved position, the affected database's cache is cleared before the stream reopens. See [health diagnostics](monitoring.md#bypass-reasons-and-stream-health) and the [permission recovery exercise](permission-recovery.md).

Bypassing still executes a MongoDB operation: database outages and driver errors can reach callers. Ineligible requests use native PyMongo behavior; invalid configuration and manager misuse raise the [documented errors](../reference/api.md#errors). Configure driver timeouts for your request and shutdown policy.

## Security

The process-local cache uses your client's connections and credentials, and stores values in application memory. It creates no listening endpoint. Anyone able to inspect process memory can read cached documents. The separate [shared-cache security model](shared-cache.md#security-and-monitoring) includes a private Unix endpoint and access to all configured databases.

Plan access changes using the [freshness and authorization guidance](../usage/consistency.md#freshness-and-authorization), and keep permission checks outside cached content retrieval.

## Connection-pool behavior

Each active cached database has one change-stream cursor. Its periodic `getMore` calls borrow connections from the client's pool for the duration of each call. Size `maxPoolSize` for one concurrent long poll per active database plus application reads and writes. The manager leaves client pool settings unchanged.

## Recovery behavior

Databases recover independently. Only healthy streams permit caching; healthy status does not promise catch-up to an independent writer's latest event.

Closing a manager first disables caching, then waits for pending startup and stream cleanup. Async `close()` finishes cleanup before propagating cancellation; concurrent closes join the same shutdown. Driver I/O can delay completion, so configure client timeouts. The manager never closes your client.

## Capacity estimation

`CacheCoreConfig(budget_bytes=..., max_entry_bytes=...)` bounds stored BSON across all collections and databases within one manager. The separate `max_namespaces` setting bounds tracked database/collection pairs; when full, other names bypass caching until a collection drop releases a slot. See the [configuration reference](../reference/api.md#configuration). These settings are not an RSS limit; keys, active cursors and application-held results add memory.

For workloads with many small results or large query filters, enable the optional retention safeguards:

```python
cache_config = CacheCoreConfig(
    budget_bytes=64 * 1024 * 1024,
    max_entries=50_000,
    max_key_bytes=16 * 1024,
)
```

Choose these example limits from measurements of your own workload. Unique-key aliases also consume slots, so `entry_count` alone does not describe count occupancy. The [API reference](../reference/api.md#optional-retention-limits) explains one-slot fallback, pair admission, occupied caches, key charging and decline observations. In-flight requests, decoded results, opaque scalar referents and allocator retention remain outside these bounds. [Shared managers](../reference/shared-cache.md) have a separate capacity policy.

One manager watching three databases opens three streams. Four workers watching those databases open twelve streams and hold four independent cache budgets. Sync and asyncio managers are also independent, even in one process. Avoid constructing a manager per request: startup and independent warming can consume the benefit before the process reuses any data.

### Memory beyond the cache budget

`budget_bytes` and `max_entry_bytes` count stored BSON. A workload with many small results or long filters can spend more memory on keys and bookkeeping than on those results. Use the optional retention safeguards and measure process memory with your application's query mix; the [API reference](../reference/api.md#optional-retention-limits) defines their bounds.

Include active requests and results held by your application when sizing a worker. A cursor still reading a miss can retain a candidate result until it finishes or closes, alongside the driver's batches. Many open cursors multiply that additional memory, so close cursors you stop reading. Library imports, clients, managers and streams also contribute to each process's baseline.

Measure after warming, eviction and shutdown. Live cache counts can fall while RSS remains high because allocators retain storage. Size container limits from measured peaks across all workers and any shared owner. The [process-memory report](https://github.com/alessio-locatelli/client-query-cache/blob/main/reports/process-memory/summary.md) records versions, workloads and measurement conditions; its observations are not an RSS guarantee.

Monitor [cache outcomes and stream health](monitoring.md) alongside your application workload. Use the [benchmark guide](../benchmarks/index.md) to decide what to measure before deployment.

### Worked worker estimate

Suppose four workers each use one manager, actively cache two databases, and have a 32 MiB `budget_bytes` setting. Together they can store up to 128 MiB of BSON and open eight database change streams. The budget covers both databases within each worker. Size each client's pool for two concurrent stream polls alongside that worker's ordinary database traffic.

Application baseline memory, retained responses and concurrent misses add to the stored BSON. Use measured per-worker peaks to set process limits. For an economic comparison, measure the application's change in CPU, memory and database usage at the same request rate, then apply your provider's prices. Read/write ratio and document size alone cannot predict the hit rate or savings.

## Multi-worker servers

Gunicorn, Uvicorn and Granian can run independent `CacheManager` instances in worker lifespans. The [FastAPI catalogue launcher](../examples/fastapi.md#running-several-workers) demonstrates this under Uvicorn. Every worker warms and retains its own data, so account for the worker count when setting budgets.

With frequent writes, independent caches can reduce read latency while increasing MongoDB CPU: every worker consumes each event and may refetch the same invalidated document. The [concurrent-write measurements](../benchmarks/index.md#multiple-workers-with-concurrent-writes) demonstrate that tradeoff. Measure application and database CPU at the same request rate.

### Shared identity reads

For repeated eligible collection reads across trusted same-host workers, consider [shared caching](shared-cache.md) and the [Granian example](../examples/fastapi-shared.md). One server avoids duplicate stored values and streams. Compare the [public measurements](../benchmarks/shared-cache.md) before changing managers.
