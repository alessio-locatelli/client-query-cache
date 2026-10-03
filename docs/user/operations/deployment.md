# Deployment

Use a long-lived manager alongside each PyMongo client you want cached. The manager owns its cached data and background streams; you own the client and its connection, credentials, TLS, and timeout settings. See [ownership](../reference/api.md#ownership) and the [installation requirements](../getting-started/installation.md).

Invalidation is asynchronous. Plan direct PyMongo reads for operations that must immediately observe a preceding write; see [consistency](../usage/consistency.md).

## Retry and error handling

- **Change-stream reconnection**: a dropped stream connection reconnects automatically using capped exponential
  backoff with jitter (starting near 100 ms, capped at 30 seconds), resuming from its last saved position. While
  reconnecting, that database's cache bypasses reads and admissions until the stream is healthy again — never
  serving from a cache that might have missed an invalidation.
- **Unresumable interruptions**: if the stream's resume position is no longer available on the server (for example,
  after an extended outage), the affected database's cache is cleared before the stream reopens, rather than assumed
  safe.
- **Errors raised to callers** are narrow and mean the caller asked for something the cache genuinely cannot do:
  `CacheConfigurationError` (invalid `CacheCoreConfig` values), `CacheClosedError` (a cached read attempted after
  `cache_manager.close()`), and `UnsupportedCacheRequestError` (`find()` with a tailable/exhaust/partial-result option, or
  `aggregate()` with a `$changeStream` pipeline — use `.raw` for these). See the
  [API reference's error table](../reference/api.md#errors) for the complete list.
- **Other cache-ineligible requests bypass.** An incompatible read preference or read concern, a session-bound
  read, a nondeterministic filter or pipeline, a view, a time-series collection, an oversized result, or a database
  whose change stream can't be established at all — each of these falls back to a normal, correct PyMongo call
  rather than raising a cache eligibility error. The underlying PyMongo call can still raise its own errors or wait for the server.

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
  process-local.

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
