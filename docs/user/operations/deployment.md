# Deployment

Use a long-lived manager alongside each PyMongo client you want cached. The manager owns its cached data and background streams; you own the client and its connection, credentials, TLS, and timeout settings. See [ownership](../reference/api.md#ownership) and the [installation requirements](../getting-started/installation.md).

Invalidation is asynchronous. Plan direct PyMongo reads for operations that must immediately observe a preceding write; see [consistency](../usage/consistency.md).

To enable caching through an application-owned deployment flag and roll it back, see the [FastAPI catalogue rollout](../examples/fastapi.md#feature-flagged-rollout).

This page describes process-local `CacheManager` deployments. To share `_id` reads and streams across workers, use the [shared worker cache](shared-cache.md).

## Retry and error handling

- **Initial stream startup**: one read starts a stream for its database. Concurrent reads for that
  database run uncached while startup is pending; other databases can start or use their caches independently.
  Failed attempts emit a warning and enter a cooldown. Retry delays are sampled between half and all of
  an exponential cap, starting at 100 ms and doubling to 30 seconds. A read at or after the deadline
  initiates the next attempt; idle databases do not retry in the background. This also applies to
  unsupported servers and denied watch permissions, so corrected deployments can recover on later reads.
- **Change-stream reconnection**: a dropped stream connection reconnects automatically using capped exponential
  backoff with jitter (starting near 100 ms, capped at 30 seconds), resuming from its last saved position. While
  reconnecting, that database's cache bypasses reads and admissions until the stream is healthy again — never
  serving from a cache that might have missed an invalidation.
- **Unresumable interruptions**: if the stream's resume position is no longer available on the server (for example,
  after an extended outage), the affected database's cache is cleared before the stream reopens, rather than assumed
  safe.
- **Errors raised to callers**: cache exceptions report invalid configuration, use after `close()`, or explicit low-level misuse. The [API reference's error table](../reference/api.md#errors) is the complete list.
- **Cache-ineligible requests bypass**: tailable, exhaust, or partial-result `find()`, `$changeStream` aggregation, and the other [bypass conditions](../reference/api.md#bypass-conditions) execute as normal PyMongo calls instead of raising a cache error. The underlying PyMongo call can still raise its own errors or wait for the server.

Use the [permission recovery exercise](permission-recovery.md) to observe startup failure, bypass counters, and read-triggered recovery on a disposable authenticated replica set.

## Security

- The cache introduces no new network exposure or authentication mechanism of its own. Every connection,
  credential, and TLS setting is entirely controlled by the PyMongo client you construct and pass to `CacheManager`
  — caching a client does not change what it's authorized to do or how it connects.
- Cached values live only in your application process's memory for the lifetime of the `CacheManager`; nothing is
  written to disk, sent over the network, or shared between processes. Treat cached documents the same as any other
  in-memory application data: anyone who can read your process's memory can read them.
- The cache does not perform its own authorization checks; a cached result reflects whatever the wrapped client was
  authorized to read when it was fetched. A cached document keeps returning from the cache until the underlying
  document changes or the entry is evicted — an unrelated permission change alone does not invalidate it. If your
  application depends on re-authorizing every read (for example, after changing a user's access), read that data
  through `.raw` instead of the cached view.

## Connection-pool behavior

Each active cached database keeps one change-stream cursor open, advanced by periodic `getMore` calls. Each
`getMore` borrows a connection from the client's own connection pool only for that call's duration — it does not
pin a connection to the cursor for its entire lifetime (outside of session-pinning cases) — so an active cached
database competes for pool connections the same way one more long-running caller would, rather than permanently
reserving one. If you activate caching for many databases through one client, size that client's `maxPoolSize` with
that many concurrent long-poll consumers in mind, alongside your application's own concurrent reads and writes.

## Recovery behavior

Each database can start, connect, become healthy, reconnect, and close independently. Caching is permitted only while its change stream is healthy; reads bypass the cache in every other state. Shutting down a manager (`cache_manager.close()`, or exiting its context manager) makes every active database unavailable before waiting for streams and background workers to stop. Close the manager before its PyMongo client; use `await cache_manager.close()` with asyncio.

Shutdown waits for pending startup and native stream cleanup. Cancelling asyncio `close()` defers
cancellation until those resources and the manager's cache are released. Concurrent or later calls
join the same shutdown. Driver I/O can delay completion; configure timeouts on your PyMongo client.

## Capacity estimation

Sizing a deployment starts from one fact: **each `CacheManager` instance opens one change-stream cursor per active
cached database it watches — not one cursor for the whole client.** A manager caching three databases through one
client keeps three cursors open, one per database, each with its own independent retry and recovery state.

This has two consequences for multi-instance or multi-process deployments:

- **A synchronous and an asyncio `CacheManager` constructed for the same MongoDB deployment in the same process do
  not share anything.** Each keeps its own memory budget (`shared_budget_bytes`) and its own change-stream cursors;
  running both to cache the same databases pays for the cursors and the budget twice.
- **Each additional process caching the same deployment multiplies the same per-instance cost again.** Ten worker
  processes each running one `CacheManager` against the same three databases open thirty change-stream cursors
  total and reserve ten independent memory budgets — none of it shared, because the cache is intentionally
  process-local. See [multi-worker servers](#multi-worker-servers).

This multiplication matters most in two shapes of deployment:

1. **A high-fan-out or short-lived-process model** — for example, one process (or one `CacheManager`) created per
   incoming request or per invocation. Opening a change-stream cursor per active database has a fixed startup cost
   that a short-lived process pays on every invocation, often without enough request volume in that one process's
   lifetime for caching to pay that cost back. Prefer a small number of long-lived `CacheManager` instances — for
   example, one created once per worker process at startup and reused across every request that worker handles —
   over constructing a new one per request.
2. **A manager caching many databases** — the number of open cursors grows with the number of active databases.
   One configured memory budget is shared across all databases and collections within that manager;
   activating another database does not increase it. If a single manager ends up watching dozens
   of databases, apportion `shared_budget_bytes` (see the [API reference](../reference/api.md#configuration)) across
   the databases and collections you actually expect concurrent hot data from, rather than leaving the default in
   place for a manager sized for a handful of databases.

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

The figures come from Python 3.14, PyMongo 4.18, and glibc on Linux, and depend on document shape. Measure your own workload before relying on them.

Monitor [cache outcomes and stream health](monitoring.md) alongside your application workload. Use the [benchmark guide](../benchmarks/index.md) to decide what to measure before deployment.

### Worked worker estimate

Suppose four workers each use one manager, actively cache two databases, and have a 32 MiB `shared_budget_bytes` setting. Together they can store up to 128 MiB of BSON and open eight database change streams. The budget is shared by the two databases within each worker; it is not 32 MiB per database. Size each client's pool for two concurrent stream polls alongside that worker's ordinary database traffic.

For the measured 4.4 KB `_id` document shape above, 128 MiB of stored BSON corresponds to about 147 MiB of added process memory across the four workers when all budgets are full. Application baseline memory, retained responses, concurrent miss captures, and other services come on top. Use observed per-worker peaks to set limits; small results or large filters can multiply the cache's memory cost much more.

For an economic comparison, measure the application's change in CPU, memory, and database usage at the same request rate, then apply your provider's prices. Read/write ratio and document size alone cannot predict the hit rate or savings.

## Multi-worker servers

Application servers such as Gunicorn, Uvicorn, and Granian can run several worker processes. Create the PyMongo client and the `CacheManager` inside each worker, for example in a FastAPI [lifespan handler](https://fastapi.tiangolo.com/advanced/events/), never in a parent process before the workers start. PyMongo [requires a new client](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/mongoclient/#multiple-forks) in each forked process.

Workers then cache independently. Each keeps its own copy of the documents it reads and its own change streams, and warms its cache on its own after it starts or restarts. For example, eight workers that each cache 100 MiB of the same hot documents hold about 800 MiB of cached data on one host and open eight change-stream cursors per cached database. Set `shared_budget_bytes` per worker with that multiplication in mind; a smaller budget lowers memory but evicts more and hits less often. Fewer workers that each serve more concurrent requests, with asyncio or threads, duplicate less.

Duplicate change streams put little load on MongoDB. In the project's measurements, seven extra streams from eight workers on one database cost MongoDB about 0.3% of a CPU core while idle and about 1% at about three writes per second; the cost grows with the write rate. With frequent writes, a cache in every worker may not reduce MongoDB load at all. In a [single-host benchmark](../benchmarks/index.md#multiple-workers-with-concurrent-writes) where four asyncio workers read 1,831 documents per second by `_id` and one update followed every 20 reads, caching cut median latency by about 40%, but MongoDB used about 10% more CPU than with direct reads. Each update reaches every worker's change stream and causes a miss in each worker that reads the document again.

### Shared identity reads

Use [SharedCacheServer](shared-cache.md) when trusted workers on one host repeatedly read the same `_id` documents. It shares those values and one stream per active database; other reads use PyMongo. Compare the [supported workload measurements](../benchmarks/shared-cache.md) with your own read mix and memory limits before choosing a mode.
