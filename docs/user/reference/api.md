# API reference

This reference covers the complete public surface of `client_query_cache`: construction, configuration, the cached
read methods, ownership rules, and how to fall back to plain PyMongo. Start with the [synchronous](../getting-started/synchronous.md) or [asyncio](../getting-started/asyncio.md) tutorial for a complete program.

Synchronous names live at the top level (`client_query_cache`) and wrap `pymongo.MongoClient`. The same names are
available under `client_query_cache.asynchronous` and wrap `pymongo.AsyncMongoClient`, with every read method
exposed as a coroutine. Everything below applies to both; only the import path and `await` differ.

## Constructing a manager

```python
from client_query_cache import CacheManager

cache_manager = CacheManager(client)
```

`CacheManager(client, *, cache_config=None, max_await_time_ms=1_000)` wraps a caller-constructed and caller-owned `MongoClient` (or
`AsyncMongoClient`). It never closes that client and never mutates it.

- `cache_manager.client` — the wrapped PyMongo client, unchanged.
- `cache_manager.cache_core` — the manager's cache storage and bookkeeping object; see [Observability](../operations/monitoring.md#observability).
- `cache_manager.cached(collection)` — a cached read view of one of your PyMongo collections; see [Cached collection views](#cached-collection-views).
- `cache_manager.close()` (`await cache_manager.close()` for asyncio) — stops every change stream the manager opened and releases cached data. Does not close `cache_manager.client`.
- `CacheManager` is also a context manager (`with` / `async with`), calling `close()` on exit.

Close the manager (or use it as a context manager) whenever you close the client it wraps. A manager starts a
background change-stream task the first time a read touches a database; leaving the manager open after closing the
client leaves that task running against a closed connection.

## Cached collection views

Keep two handles for a collection: PyMongo's own collection for writes, administration, and any read you don't want cached, and a cached view of it for the six cached reads.

```python
collection = client["my_database"]["my_collection"]
cached_collection = cache_manager.cached(collection)

collection.insert_one({"_id": "example", "value": 42})
cached_collection.find_one({"_id": "example"})
```

The asyncio version is identical except that both calls are awaited:

```python
collection = client["my_database"]["my_collection"]
cached_collection = cache_manager.cached(collection)

await collection.insert_one({"_id": "example", "value": 42})
await cached_collection.find_one({"_id": "example"})
```

`cache_manager.cached(collection)` returns a `CachedCollection` whose `.raw` is exactly the collection you passed, including options you chose with `get_collection(...)` or `with_options(...)` — those options decide whether a read can use the cache (see [Bypass conditions](#bypass-conditions)). The collection must come from the manager's own client; a collection from any other client raises `ValueError`.

Calling `cached(collection)` more than once is safe and cheap: every view from one manager shares that manager's cache and its single change stream per database, so a result cached through one view is a hit through another. Each call may return a new view object, so don't rely on two views being the same object; keep one around when convenient.

`cache_manager[name]` returns a `CachedDatabase`, and `database[name]` returns a `CachedCollection`, as a shorthand for cached reads when you don't already hold a PyMongo collection. Attribute access (`database.users`, `cached_collection.chunks`) also returns a cached view of that collection or sub-collection. Index access always works, including for a collection named like a PyMongo method (`database["create_collection"]`).

- `CachedDatabase.name`, `CachedCollection.name` — the wrapped object's name.
- `CachedDatabase.raw`, `CachedCollection.raw` — the wrapped PyMongo `Database`/`Collection`; see [Raw fallback](#raw-fallback).
- `CachedDatabase.manager` — the owning `CacheManager`.
- `CachedCollection.database` — the owning `CachedDatabase`.

Cached views expose nothing else. PyMongo methods such as `insert_one`, `create_index`, `drop`, `with_options`, or `create_collection` raise `AttributeError` on a view — call them on your PyMongo object or on `.raw`.

## Cached read methods

`CachedCollection` provides `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, and `distinct`. Eligible reads can reuse cached results; ineligible reads execute through PyMongo. Cached views remain read-only: writes and other methods belong on the PyMongo collection or `.raw`.

`find()` returns a native `Cursor` subclass synchronously or an `AsyncCursor` subclass immediately with asyncio. Construction validates arguments locally and performs no database read or cache lookup. Consume the cursor to begin execution. `aggregate()` returns a `CommandCursor`; with asyncio, await it to receive an `AsyncCommandCursor`. A miss or bypass executes the initial aggregation command before returning.

```python
with cached_collection.find({"status": "active"}).sort("name").limit(10) as cursor:
    for product in cursor:
        print(product)
items = cached_collection.find({"status": "active"}).to_list()
summary = cached_collection.aggregate([{"$match": {"status": "active"}}]).to_list()
```

With asyncio, use `async for product in cached_collection.find(...)`, or `await cached_collection.find(...).to_list()` for a list. For aggregation, first use `cursor = await cached_collection.aggregate(...)`, then `await cursor.to_list()`. Async cursor contexts use `async with`.

Misses stream through native batching. The cache admits only successfully consumed complete results: partial `to_list(length=...)`, early close, errors, cancellation, or invalidation during consumption prevent incomplete or stale admission. Continue consuming a partial cursor to finish its result. Close cursors you abandon; closing a cursor never closes the client.

Find sorting, skipping, limits, and collation determine the final query and its cache identity. Clone, copy, rewind, and supported synchronous indexing use native query semantics and check current cache eligibility for their new execution. Async indexing raises the native error. Unsupported options and operations execute natively, including hints, comments, timeouts, arbitrary flags, `explain()`, and cursor `distinct()`.

A positive integer find limit can reuse an isolated prefix of a complete, valid cached query with an equal or larger positive limit, or an unlimited integer-zero/omitted limit. Every other final query input must match, including filter representation, projection, ordered sort, skip, collation, namespace, and codec options. Smaller sources cannot cover larger requests. Unlimited, negative, and boolean requests use exact lookup only; negative and boolean sources cannot cover other limits. A local find hit's `retrieved` counts the loaded prefix, and the cursor has no server cursor, address, or session. See the [complete-consumption example](../usage/cached-reads.md#read-methods) and [consistency limits](../usage/consistency.md).

Explicit find batching before execution and aggregate `batchSize` at invocation bypass caching. Later command-cursor `batch_size()` calls retain native validation and return the same cursor: they change future native getMore batching on a miss or bypass, while a local hit remains local and issues no command.

A started hit consumes one isolated snapshot, even if a write, stream interruption, eviction, or manager closure follows. Hit metadata reports `cursor_id == 0`, `address is None`, and `session is None`; `alive` reflects unread documents. A find hit's `collection` is the wrapped PyMongo collection, and `retrieved` counts documents loaded into its buffer. Hits skip server query execution, so they cannot reproduce fresh server/network errors or server-side query effects. Use `.raw` whenever execution itself is required.

## Single-document reads

Both synchronous and asyncio views accept
`find_one(filter=None, projection=None, *, sort=None, collation=None, session=None, **kwargs)`
and return a document or `None`. Deterministic filters, including compound predicates, regular expressions and
match-all reads, can be cached. Repeated missing results can also hit the cache.

```python
cached_collection.find_one(
    {"status": "active", "region": "Europe"},
    {"name": 1, "_id": 0},
    sort=[("priority", -1), ("name", 1)],
    collation={"locale": "en", "strength": 2},
)
```

Use `await` with the same arguments on an asyncio view. `sort` accepts a sequence of field/direction pairs,
with directions `1` or `-1`; collation accepts a PyMongo `Collation` or a dictionary. Omitting collation uses
the collection default. Sorting follows MongoDB's ordering guarantees, including its handling of ties.
Different filters, projections, sorts, collations and decoding options retain their own results.

Exact `_id` lookups under simple collation and qualifying unique indexes can retain a cached result after
writes to other documents. Partial, sparse and hashed indexes do not qualify for this optimization.
Unique-index collation must have a confirmed match: inherited defaults and fully specified explicit matches
qualify; an explicit collation with omitted defaults may use collection-wide invalidation instead.
Other eligible single-document queries are refreshed after any write to the collection, including writes
that could introduce a match for a cached missing result.

Cache invalidation is eventual. A cached read can return its previous value until the manager processes
the relevant change-stream event. Use the PyMongo collection or a session-bound read when you need to
immediately observe a preceding write. Additional keyword options execute directly through PyMongo;
malformed arguments preserve the driver's errors.

## Bypass conditions

A read bypasses the cache — executing as a normal PyMongo call instead of a lookup or admission — whenever caching
it safely isn't possible:

- The caller supplies a session or uses `session.bind()`, a read preference other than primary, or a read concern other than majority.
  Leaving read concern unspecified (the common case) is treated as compatible with caching, not as a bypass
  condition: a cache miss reads at majority concern, which is stronger, and can be slower or less available during a
  network partition, than the server's own default read concern an uncached call would otherwise use.
- Find cursor-only requests (tailable, exhaust, partial results), explicit find batching, unsupported find options, and aggregation batching supplied at invocation execute natively. `$changeStream` pipelines also execute natively without caching.
- The collection is a MongoDB view.
- An aggregation pipeline joins another collection, writes, reports live statistics, or is otherwise
  nondeterministic (for example a `$sample` stage or a `$rand` expression).
- A `find_one`, `find`, `count_documents`, or `distinct` filter is nondeterministic.
- The collection is a time-series collection — MongoDB does not provide change streams for time-series collections,
  so caching bypasses unconditionally for them. If a time-series collection is later replaced with an ordinary
  collection, reads may keep bypassing until a new manager is created, since MongoDB supplies no notification that
  refreshes a collection's type once it's been determined to be time-series.
- The target collection does not yet exist. Later reads recheck its type: a missing document in an existing
  ordinary collection can still be cached, and a namespace later created as an ordinary collection can be cached
  normally from then on.
- The manager's change stream for that database can't be established at all (an unsupported MongoDB version or
  topology; see [system requirements](../getting-started/installation.md#requirements)) or is temporarily unhealthy (see
  [recovery behavior](../operations/deployment.md#recovery-behavior)).

## Configuration

Pass a `CacheCoreConfig` to size a manager's cache:

```python
from client_query_cache import CacheCoreConfig, CacheManager

cache_manager = CacheManager(
    client, cache_config=CacheCoreConfig(shared_budget_bytes=128 * 1024 * 1024)
)
```

| Field                       | Default                  | Meaning                                                                                                                                                                                                                                                                                                   |
| --------------------------- | ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `shared_budget_bytes`       | 64 MiB                   | Total BSON-encoded size the manager's cache may hold at once, shared across every database and collection that manager caches.                                                                                                                                                                            |
| `max_entry_bytes`           | 1 MiB                    | The largest single cached value (one document, or one `find`/`aggregate`/`distinct` result) the cache accepts.                                                                                                                                                                                            |
| `lag_capture_window_config` | 10 windows of 100 events | Sizes the invalidation-lag sample windows used by the stream-cost telemetry described in [Observability](../operations/monitoring.md#observability). Most applications never need to change this; it exists for the benchmark suite documented in [stream cost benchmarks](../benchmarks/stream-cost.md). |

`CacheCoreConfig` raises `CacheConfigurationError` if `shared_budget_bytes` or `max_entry_bytes` is not positive, or
if `max_entry_bytes` exceeds `shared_budget_bytes`.

### Change-stream await time

Set `max_await_time_ms` directly on either manager to choose the maximum idle server wait for a change-stream batch:

```python
cache_manager = CacheManager(client, max_await_time_ms=5_000)
```

The default is 1,000 ms. Each manager keeps its own setting across its databases and reconnects. Values must be
integers from 1 through 2,147,483,647; booleans and other invalid values raise `CacheConfigurationError` at
construction.

See the [await-time measurements](../benchmarks/stream-cost.md#change-stream-await-time) for the default's
selection rule, retained evidence, and limitations.

This bounds an idle `getMore` wait. Event delivery and failure detection also depend on the server, network, and
client timeouts. If you set a nonzero PyMongo `timeoutMS`, it must be greater than `max_await_time_ms`, as required
by the [driver's change-stream timeout rules](https://github.com/mongodb/specifications/blob/master/source/client-side-operations-timeout/client-side-operations-timeout.md#change-streams).
Consider `socketTimeoutMS` and network infrastructure idle timeouts when choosing a value; the manager leaves
your client's timeout settings unchanged.

## Limits

- A read whose result would exceed `max_entry_bytes` once BSON-encoded is not cached; it still returns the correct
  result, counted as an oversized bypass rather than a hit.
- Cursor candidates also cap their retained encoded payload at `max_entry_bytes`; exceeding it discards the candidate while native delivery continues. Native batches, decoded hit snapshots, wrappers, and temporary encoding allocations consume additional memory. This is not a process-memory limit.
- Once the cache's total stored BSON size would exceed `shared_budget_bytes`, admitting a new entry evicts the
  least-recently-used entries to make room. Query keys and Python metadata consume additional memory outside
  this budget, especially for large predicates with small results.
- A read whose `_id` or result depends on a value that cannot be used as a cache key — for example a `bson.Code`
  value, or a `NaN`, which is never equal to itself — is executed and returned normally without being cached.

None of these limits raise an exception to the caller: exceeding one always falls back to an uncached, correct
result. See [deployment guidance](../operations/deployment.md#capacity-estimation) for how to size these limits against your
deployment.

## Ownership

`CacheManager` constructs and exclusively owns one cache core (`CacheCore`) and one change-stream coordinator
(`ChangeStreamCoordinator`) for its own lifetime; it does not share either with another manager. `CacheCore` and
`ChangeStreamCoordinator` are also exported directly (`client_query_cache.synchronous` /
`client_query_cache.asynchronous`) for advanced use, but constructing them yourself and sharing one `CacheCore`
across more than one `ChangeStreamCoordinator` — or activating the same database from two coordinators over one
`CacheCore` — is unsupported.

The reason is availability tracking, not locking: a `CacheCore` records whether a database's change stream is
healthy as a single flag per database, not one flag per coordinator that might be watching it. If two coordinators
shared a `CacheCore`, one of them stopping (its own shutdown, a fatal reconnect failure) would overwrite that shared
flag and could silently mark another, still-healthy coordinator's database unavailable — cached reads for that
database would then bypass with no error or warning pointing at the actual cause.

Construct one `CacheManager` per `MongoClient` (or `AsyncMongoClient`) you want cached. Two managers wrapping the
same underlying deployment — a synchronous and an asyncio manager in the same process, or one manager per process —
each keep an independent budget and independent change-stream cursors; see
[deployment guidance](../operations/deployment.md#capacity-estimation) for the capacity consequence of that duplication.

## Raw fallback

Every wrapped object exposes the PyMongo object underneath:

- `cached_collection.raw` — the wrapped `pymongo.Collection` (or its asyncio equivalent).
- `database.raw` — the wrapped `pymongo.Database`.
- `cache_manager.client` — the wrapped `pymongo.MongoClient` (or `AsyncMongoClient`).

`.raw` is typed as PyMongo's own class, so your editor and type checker see PyMongo's real signatures for every call made through it. Use it for writes and administration when you only hold a view, and for PyMongo's own semantics of the six cached method names — reads that must execute against MongoDB even when a cached result exists. Calls through `.raw` never use the cache.

## Rollback to plain PyMongo

Because `CacheManager` wraps a client you already own rather than replacing it, removing the cache layer is a mechanical change: make each `cached_collection` read on the PyMongo collection instead, wrapping `find()` and `aggregate()` in `list(...)` where your code needs a list. Writes and administration already go through PyMongo and need no change. No data migration is needed either — the manager never alters stored documents, it only caches read results in your process's memory.

## Errors

Import the cache exceptions from `client_query_cache`:

```python
from client_query_cache import (
    CacheClosedError,
    CacheConfigurationError,
    CacheError,
    UnsupportedCacheRequestError,
)
```

The three cache exceptions below inherit from `CacheError`, which you can catch to handle them together.
The same exception classes apply to synchronous and asyncio managers.

| Exception                      | Raised when                                                                       | What to do                                                         |
| ------------------------------ | --------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `CacheConfigurationError`      | A `CacheCoreConfig` value or the manager's `max_await_time_ms` is invalid.        | Fix the configuration value.                                       |
| `CacheClosedError`             | A cached read is attempted after `cache_manager.close()`.                         | Don't use a manager (or a view obtained from it) after closing it. |
| `UnsupportedCacheRequestError` | An explicit low-level cache operation receives an unsupported key value.          | Use a supported key or the native collection.                      |
| `ValueError`                   | `cache_manager.cached(collection)` receives a collection from a different client. | Pass a collection from `cache_manager.client`.                     |

Every other unsupported or ambiguous condition — an incompatible read preference or read concern, a session-bound
read, a nondeterministic filter or pipeline, a view, a time-series collection, an oversized result, a database whose
change stream isn't healthy or can't be established — bypasses the cache and returns a normal PyMongo result instead
of raising. See [deployment guidance](../operations/deployment.md#retry-and-error-handling) for stream-level failures, which
are retried internally rather than surfaced to callers at all.

## Diagnostics

Both manager variants provide synchronous, read-only local inspection, including after close:

```python
from client_query_cache import CacheSnapshot, StreamCostSnapshot, StreamHealthSnapshot

snapshot: CacheSnapshot = manager.snapshot()
stream_cost: StreamCostSnapshot = manager.stream_cost_snapshot("shop")
stream_health: StreamHealthSnapshot = manager.stream_health_snapshot("shop")
measured_databases = manager.active_stream_cost_databases()
```

Snapshots contain cumulative cache counters and capacity observations without document contents or queries.
Inspection does not activate a stream or make a database request. The advanced `manager.cache_core`
inspection methods remain available.

`CacheSnapshot`, `BypassReason`, `BypassReasonCount`, `StreamCostSnapshot`, `StreamHealthSnapshot`, and
`StreamHealthStatus` are importable from `client_query_cache`, `client_query_cache.synchronous`, and
`client_query_cache.asynchronous`. See [bypass reasons and stream health](../operations/monitoring.md#bypass-reasons-and-stream-health)
for their meaning and limitations.
