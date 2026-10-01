# API reference

This reference covers the complete public surface of `client_query_cache`: construction, configuration, the cached
read methods, ownership rules, and how to fall back to plain PyMongo. See the [README](../README.md) for the
conceptual overview and a quick start.

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
- `cache_manager.cache_core` — the manager's cache storage and bookkeeping object; see [Observability](architecture.md#observability).
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

`CachedCollection` exposes six read methods named after their PyMongo equivalents and accepting their arguments: `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, and `distinct`. Each either returns a cached result, admits a fresh result to the cache, or transparently bypasses to a direct PyMongo call — see [Bypass conditions](#bypass-conditions) below for what decides which of the three happens. Two methods return something different from their PyMongo counterparts:

- `find()` always returns a fully materialized `list`, not a cursor, and raises `UnsupportedCacheRequestError` if called with an option that only makes sense for a cursor (`cursor_type` other than `NON_TAILABLE`, or `allow_partial_results=True`). In asyncio, you `await` `find()` for that list. Use `cached_collection.raw.find(...)` for a cursor.
- `aggregate()` also always fully materializes its result into a `list` and raises `UnsupportedCacheRequestError` if the pipeline contains a `$changeStream` stage, since that cursor has no natural end to materialize toward. Use `cached_collection.raw.aggregate(...)` for a change-stream pipeline.

Every other method — all writes, and every other read (`find_one_and_update`, `find_raw_batches`, index management, and so on) — belongs on the PyMongo object.

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

- The caller supplies a session, a read preference other than primary, or a read concern other than majority.
  Leaving read concern unspecified (the common case) is treated as compatible with caching, not as a bypass
  condition: a cache miss reads at majority concern, which is stronger, and can be slower or less available during a
  network partition, than the server's own default read concern an uncached call would otherwise use.
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
  topology; see [system requirements](architecture.md#system-requirements)) or is temporarily unhealthy (see
  [recovery behavior](architecture.md#recovery-behavior)).

## Configuration

Pass a `CacheCoreConfig` to size a manager's cache:

```python
from client_query_cache import CacheCoreConfig, CacheManager

cache_manager = CacheManager(
    client, cache_config=CacheCoreConfig(shared_budget_bytes=128 * 1024 * 1024)
)
```

| Field                       | Default                  | Meaning                                                                                                                                                                                                                                                                                         |
| --------------------------- | ------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `shared_budget_bytes`       | 64 MiB                   | Total BSON-encoded size the manager's cache may hold at once, shared across every database and collection that manager caches.                                                                                                                                                                  |
| `max_entry_bytes`           | 1 MiB                    | The largest single cached value (one document, or one `find`/`aggregate`/`distinct` result) the cache accepts.                                                                                                                                                                                  |
| `lag_capture_window_config` | 10 windows of 100 events | Sizes the invalidation-lag sample windows used by the stream-cost telemetry described in [Observability](architecture.md#observability). Most applications never need to change this; it exists for the benchmark suite documented in [`stream-cost-benchmarks.md`](stream-cost-benchmarks.md). |

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

See the [await-time measurements](stream-cost-benchmarks.md#change-stream-await-time) for the default's
selection rule, retained evidence, and limitations.

This bounds an idle `getMore` wait. Event delivery and failure detection also depend on the server, network, and
client timeouts. If you set a nonzero PyMongo `timeoutMS`, it must be greater than `max_await_time_ms`, as required
by the [driver's change-stream timeout rules](https://github.com/mongodb/specifications/blob/master/source/client-side-operations-timeout/client-side-operations-timeout.md#change-streams).
Consider `socketTimeoutMS` and network infrastructure idle timeouts when choosing a value; the manager leaves
your client's timeout settings unchanged.

## Limits

- A read whose result would exceed `max_entry_bytes` once BSON-encoded is not cached; it still returns the correct
  result, counted as an oversized bypass rather than a hit.
- Once the cache's total resident size would exceed `shared_budget_bytes`, admitting a new entry evicts the
  least-recently-used entries to make room.
- A read whose `_id` or result depends on a value that cannot be used as a cache key — for example a `bson.Code`
  value, or a `NaN`, which is never equal to itself — is executed and returned normally without being cached.

None of these limits raise an exception to the caller: exceeding one always falls back to an uncached, correct
result. See [`docs/architecture.md`](architecture.md#capacity-estimation) for how to size these limits against your
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
[`docs/architecture.md`](architecture.md#capacity-estimation) for the capacity consequence of that duplication.

## Raw fallback

Every wrapped object exposes the PyMongo object underneath:

- `cached_collection.raw` — the wrapped `pymongo.Collection` (or its asyncio equivalent).
- `database.raw` — the wrapped `pymongo.Database`.
- `cache_manager.client` — the wrapped `pymongo.MongoClient` (or `AsyncMongoClient`).

`.raw` is typed as PyMongo's own class, so your editor and type checker see PyMongo's real signatures for every call made through it. Use it for writes and administration when you only hold a view, and for PyMongo's own semantics of the six cached method names — `find()` with a cursor, or `aggregate()` with a `$changeStream` pipeline. Calls through `.raw` never use the cache.

## Rollback to plain PyMongo

Because `CacheManager` wraps a client you already own rather than replacing it, removing the cache layer is a mechanical change: make each `cached_collection` read on the PyMongo collection instead, wrapping `find()` and `aggregate()` in `list(...)` where your code needs a list. Writes and administration already go through PyMongo and need no change. No data migration is needed either — the manager never alters stored documents, it only caches read results in your process's memory.

## Errors

| Exception                      | Raised when                                                                                                                   | What to do                                                         |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `CacheConfigurationError`      | A `CacheCoreConfig` value is invalid (non-positive, or `max_entry_bytes` exceeds `shared_budget_bytes`).                      | Fix the configuration value.                                       |
| `CacheClosedError`             | A cached read is attempted after `cache_manager.close()`.                                                                     | Don't use a manager (or a view obtained from it) after closing it. |
| `UnsupportedCacheRequestError` | `find()` is called with a tailable/exhaust/partial-result option, or `aggregate()` is called with a `$changeStream` pipeline. | Use `.raw` for that call.                                          |
| `ValueError`                   | `cache_manager.cached(collection)` receives a collection from a different client.                                             | Pass a collection from `cache_manager.client`.                     |

Every other unsupported or ambiguous condition — an incompatible read preference or read concern, a session-bound
read, a nondeterministic filter or pipeline, a view, a time-series collection, an oversized result, a database whose
change stream isn't healthy or can't be established — bypasses the cache and returns a normal PyMongo result instead
of raising. See [`docs/architecture.md`](architecture.md#retry-and-error-handling) for stream-level failures, which
are retried internally rather than surfaced to callers at all.
