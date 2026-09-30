# Architecture and operations

This document covers what an operator needs to run `client-query-cache` in production: system requirements,
capacity planning, retry and error behavior, observability, security boundaries, connection-pool impact, and
recovery behavior. See the [README](../README.md) for the conceptual overview and the
[API reference](api-reference.md) for the complete public surface.

## System requirements

- **MongoDB 8.0 or newer, running as a replica set or sharded cluster.** Change streams — the mechanism this cache
  uses to learn about writes — are not available against a standalone server. Against a server or topology that
  can't provide them, the manager doesn't raise; it logs a warning and every read for that database bypasses the
  cache, falling back to a normal PyMongo call.
- **Python 3.14.6 or newer** and **pymongo 4.18.1 or newer** (the versions this package declares as its own
  requirements).
- No additional infrastructure. The cache lives entirely in your application process's memory; it needs nothing
  beyond the MongoDB deployment you already connect to — no separate cache server, no shared external store.

## High-level design

```text
your application code
        │
        ▼
CachedCollection / CachedDatabase   (view: find_one, find, aggregate, count_documents,
        │                            estimated_document_count, distinct — everything else
        │                            called on the PyMongo object or `.raw`)
        ▼
   CacheManager                     (one per MongoClient/AsyncMongoClient you want cached)
        │
        ├── CacheCore               (bounded in-memory storage, hit/miss/eviction bookkeeping)
        │
        └── ChangeStreamCoordinator (one DatabaseStreamSupervisor per active cached database)
                    │
                    ▼
        MongoDB change stream(s)    (one cursor per active cached database)
```

A read against a `CachedCollection` either returns a cached value, executes against MongoDB and admits the result
to the cache, or bypasses the cache entirely and executes a normal PyMongo call — see the README for exactly which
of the three applies. `ChangeStreamCoordinator` starts one `DatabaseStreamSupervisor` per database the first time a
read touches it; each supervisor watches that one database and invalidates affected cache entries in `CacheCore` as
writes and schema changes occur.

## Low-level design

- **Cache granularity**: entries are scoped to a MongoDB namespace (`database.collection`), then further scoped
  within it. A read resolved to one document — by `_id`, or by a value in a field a unique index enforces — is
  cached and invalidated per document, so a write to one document never invalidates another document's cached
  entry. A read with no such resolved identity (a bounded `find`/`aggregate`/`count_documents`/`distinct` result) is
  cached and invalidated as a whole namespace: any write to that collection invalidates every such cached result for
  it, regardless of which document the write touched.
- **Unique-key discovery**: the facade discovers which fields can resolve a single-document lookup from the
  collection's own index metadata (a plain, non-partial, non-sparse, non-hashed unique index whose collation matches
  the read) — there is nothing to declare, and discovery is re-checked whenever an index is added or removed.
- **Coherency model**: coherency is bounded and eventual, not synchronous. A cache hit that runs concurrently with
  an independent write may still return the pre-write value until this library's change-stream worker processes
  that write's event; once processed, every later read is guaranteed to see the invalidation. This is not a
  per-write barrier — it does not wait for "catch-up" on every read, only guarantees that a processed write is never
  silently missed.

### Why only reads are cached

Writes always execute directly against MongoDB through PyMongo's own collection or `.raw`; the cache never intercepts or replays one. Once the manager processes the change-stream event a write produced, it invalidates every cached result the write could have affected, so the next read re-fetches instead of returning stale data — that invalidation step is sufficient on its own to keep the cache correct, without the cache needing to know what a write changed. Populating the cache directly from a write's own response isn't done either: many PyMongo write calls (an update, an upsert) don't return the resulting document at all, so caching "the write result" would still require an extra read to get one. Letting the next real read repopulate the cache after invalidation is simpler and correct in every case, rather than only the cases where a write happens to hand back a usable document.

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
  [API reference's error table](api-reference.md#errors) for the complete list.
- **Everything else bypasses instead of raising.** An incompatible read preference or read concern, a session-bound
  read, a nondeterministic filter or pipeline, a view, a time-series collection, an oversized result, or a database
  whose change stream can't be established at all — each of these falls back to a normal, correct PyMongo call
  rather than raising or blocking.

## Observability

- **Logging**: every component logs through the standard `logging` module under `client_query_cache.*` logger
  names (for example, `client_query_cache.synchronous.streams` logs stream reconnects and shutdown warnings). Attach
  handlers the same way you would for any other library; no separate configuration mechanism exists.
- **Runtime cache statistics**: `cache_manager.cache_core.snapshot()` returns an immutable snapshot with the manager's
  lifecycle state, resident bytes, configured budget and max entry size, entry count, and cumulative hits, misses,
  evictions, bypasses, and oversized bypasses. None of these fields expose document contents, queries, or
  credentials, so the snapshot is safe to log or export to a metrics system directly.
- **Per-database stream telemetry**: `cache_manager.cache_core.stream_cost_snapshot(database_name)` returns manager iteration-call counts,
  logical event bytes, invalidation counts, and invalidation-delivery-lag samples for one database, and
  `cache_manager.cache_core.active_stream_cost_databases()` lists which databases currently have telemetry. This is the
  same telemetry the [stream-cost benchmark suite](stream-cost-benchmarks.md) uses; the lag samples carry an
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
register_cache_metrics(meter, cache_manager.cache_core)
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

The lag gauge reports a simple order-statistic quantile over the samples the manager currently retains — a live,
at-a-glance figure, not the calibrated, confidence-interval estimate the
[stream-cost benchmark suite](stream-cost-benchmarks.md) produces for report-grade claims. It carries the same
clock-skew disclaimer as the underlying stream telemetry.

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

Each database's change-stream supervisor moves through a small set of states: starting, connecting, healthy,
reconnecting, and closed. Caching is only permitted while a database's supervisor reports healthy; every other state
bypasses cache use for that database. Shutting down a manager (`cache_manager.close()`, or exiting it as a context
manager) marks every active database unavailable _before_ it waits for a stream or its background worker to stop —
so a slow shutdown never leaves a window where reads could still hit a cache that is mid-teardown.

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
2. **A manager caching many databases** — both the number of open cursors and the size of the shared memory budget
   scale linearly with the number of active databases on that manager. If a single manager ends up watching dozens
   of databases, apportion `shared_budget_bytes` (see the [API reference](api-reference.md#configuration)) across
   the databases and collections you actually expect concurrent hot data from, rather than leaving the default in
   place for a manager sized for a handful of databases.
