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

`CacheCoreConfig(shared_budget_bytes=..., max_entry_bytes=...)` bounds stored BSON across all collections and databases within one manager. Despite its name, `shared_budget_bytes` does not share values between processes. The separate `max_namespaces` setting bounds tracked database/collection pairs; when full, other names bypass caching until a collection drop releases a slot. See the [configuration reference](../reference/api.md#configuration). These settings are not an RSS limit; keys, active cursors and application-held results add memory.

One manager watching three databases opens three streams. Four workers watching those databases open twelve streams and hold four independent cache budgets. Sync and asyncio managers are also independent, even in one process. Avoid constructing a manager per request: startup and independent warming can consume the benefit before the process reuses any data.

### Memory beyond the cache budget

`shared_budget_bytes` and `max_entry_bytes` count stored BSON, not process memory. Each cached result also keeps its query and some bookkeeping: from about 0.6 KB for a document read by `_id` to about 0.9 KB for a result found by a short filter, plus the filter values your application passed. Large results barely notice this; many small results multiply it. In the project's measurements, a full budget added this much process memory beyond the same reads without the cache:

| Cached results                                    | Added memory per cached result | Added memory per 1 MiB of cached BSON |
| ------------------------------------------------- | -----------------------------: | ------------------------------------: |
| `find()` results of about 0.9 MiB                 |                    about 1 MiB |                        about 1.05 MiB |
| 4.4 KB documents read by `_id`                    |                   about 4.9 KB |                        about 1.15 MiB |
| 60-byte results read with a one-field filter      |                   about 0.9 KB |                          about 15 MiB |
| 60-byte results read with a 48-value `$in` filter |                   about 4.5 KB |                          about 77 MiB |

For example, the default 64 MiB budget filled with 4.4 KB documents added about 74 MiB, while a 4 MiB budget filled with 60-byte results from the larger filter added about 310 MiB. If most cached results are small, or filters carry long lists of values, lower `shared_budget_bytes` and compare `entry_count` from [`snapshot()`](monitoring.md#observability) with your process memory.

Other memory comes on top of the budget:

- A cursor that is still reading a miss keeps a copy of what it has read so far, up to `max_entry_bytes`, until it finishes or closes. Thirty-two open cursors that had each read about 0.9 MiB added 31–34 MiB. Close cursors you stop reading.
- Results your application keeps take the same memory as without the cache.
- Importing the library and running one manager added about 2 MiB to a process before any result was cached.

Process memory usually stays near its peak after the cache frees memory. After eviction, closing cursors, or closing the manager, Python and the C library keep freed memory for reuse instead of returning it to the operating system. Closing a manager that had filled its budget typically left 0–20 MiB above the starting level after large results or documents, and 20–62 MiB after many small results, the most with large filters. Five fill-and-close cycles in one process reused that memory: their peaks barely grew after the first cycle. Size memory limits for the observed peak, not for the current budget usage.

Container memory limits apply to the container's own memory counter, not to process RSS, which also counts shared library pages. In the measurements, the container counter followed the process's private memory and stayed about 17 MiB below RSS.

The figures come from Python 3.14, PyMongo 4.18, and glibc on Linux; see the [memory measurement report](https://github.com/alessio-locatelli/client-query-cache/blob/main/reports/process-memory/summary.md) for commands and evidence. Measure your own document and query shapes.

Monitor [cache outcomes and stream health](monitoring.md) alongside your application workload. Use the [benchmark guide](../benchmarks/index.md) to decide what to measure before deployment.

### Worked worker estimate

Suppose four workers each use one manager, actively cache two databases, and have a 32 MiB `shared_budget_bytes` setting. Together they can store up to 128 MiB of BSON and open eight database change streams. The budget is shared by the two databases within each worker; it is not 32 MiB per database. Size each client's pool for two concurrent stream polls alongside that worker's ordinary database traffic.

For the measured 4.4 KB `_id` document shape above, 128 MiB of stored BSON corresponds to about 147 MiB of added process memory across the four workers when all budgets are full. Application baseline memory, retained responses, concurrent miss captures, and other services come on top. Use observed per-worker peaks to set limits; small results or large filters can multiply the cache's memory cost much more.

For an economic comparison, measure the application's change in CPU, memory, and database usage at the same request rate, then apply your provider's prices. Read/write ratio and document size alone cannot predict the hit rate or savings.

## Multi-worker servers

Gunicorn, Uvicorn and Granian can run independent `CacheManager` instances in worker lifespans. The [FastAPI catalogue launcher](../examples/fastapi.md#running-several-workers) demonstrates this under Uvicorn. Every worker warms and retains its own data, so account for the worker count when setting budgets.

With frequent writes, independent caches can reduce read latency while increasing MongoDB CPU: every worker consumes each event and may refetch the same invalidated document. The [concurrent-write measurements](../benchmarks/index.md#multiple-workers-with-concurrent-writes) demonstrate that tradeoff. Measure application and database CPU at the same request rate.

### Shared identity reads

For repeated exact `_id` reads across trusted same-host workers, consider [shared caching](shared-cache.md) and the [Granian example](../examples/fastapi-shared.md). One server avoids duplicate stored values and streams. Broader query results are not shared; compare the [public measurements](../benchmarks/shared-cache.md) before changing managers.
