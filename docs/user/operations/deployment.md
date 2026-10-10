# Deployment

Use a long-lived manager alongside each PyMongo client you want cached. The manager owns its cached data and background streams; you own the client and its connection, credentials, TLS, and timeout settings. See [ownership](../reference/api.md#ownership) and the [installation requirements](../getting-started/installation.md).

Invalidation is asynchronous. Plan direct PyMongo reads for operations that must immediately observe a preceding write; see [consistency](../usage/consistency.md).

To enable caching through an application-owned deployment flag and roll it back, see the [FastAPI catalogue rollout](../examples/fastapi.md#feature-flagged-rollout).

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

Monitor [cache outcomes and stream health](monitoring.md) alongside your application workload. Use the [benchmark guide](../benchmarks/index.md) to decide what to measure before deployment.

## Multi-worker servers

Application servers such as Gunicorn, Uvicorn, and Granian can run several worker processes. Create the PyMongo client and the `CacheManager` inside each worker, for example in a FastAPI [lifespan handler](https://fastapi.tiangolo.com/advanced/events/), never in a parent process before the workers start. PyMongo [requires a new client](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/connect/mongoclient/#multiple-forks) in each forked process.

Workers then cache independently. Each keeps its own copy of the documents it reads and its own change streams, and warms its cache on its own after it starts or restarts. For example, eight workers that each cache 100 MiB of the same hot documents hold about 800 MiB of cached data on one host and open eight change-stream cursors per cached database. Set `shared_budget_bytes` per worker with that multiplication in mind; a smaller budget lowers memory but evicts more and hits less often. Fewer workers that each serve more concurrent requests, with asyncio or threads, duplicate less.

Duplicate change streams put little load on MongoDB. In the project's measurements, seven extra streams from eight workers on one database cost MongoDB about 0.3% of a CPU core while idle and about 1% at about three writes per second; the cost grows with the write rate.

### Memory versus CPU in the cloud

The library does not share one cache across worker processes, because sharing saves memory but costs more CPU. In a research prototype, eight workers that read through one shared cache process per host used half as much memory. However, every cached read then needed a request to that process, so each read cost about 1.7 times as much CPU and request tail latency rose by a third or more.

In that prototype, eight workers each caching about 70 MiB saved about 0.5 GiB per host, while at about 1,300 cached reads per second they used about a quarter of a vCPU more. The memory saved grows with cache size and worker count, while the extra CPU grows with cached reads per second. The measurements cover one host and small documents read by `_id`; larger documents or a faster shared design could change the balance.

To compare the two for your own deployment, price them with your provider's rates. As an illustration only, assume one vCPU costs as much as 8 GiB of memory: the extra quarter of a vCPU then costs as much as about 2 GiB, roughly four times the 0.5 GiB saved. Under that assumption, sharing would pay off only for a large cache read at a low rate.

[Issue #229](https://github.com/alessio-locatelli/client-query-cache/issues/229) tracks reducing the shared-cache CPU overhead, and [issue #87](https://github.com/alessio-locatelli/client-query-cache/issues/87) tracks sharing change streams across processes. Maintainers can read the [shared cache research](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/research/shared-worker-cache-feasibility.md) and the [shared invalidation research](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/research/shared-invalidation-feasibility.md) for the measurements and their limits.
