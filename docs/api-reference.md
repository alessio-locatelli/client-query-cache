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

manager = CacheManager(client)
```

`CacheManager(client, *, cache_config=None)` wraps a caller-constructed and caller-owned `MongoClient` (or
`AsyncMongoClient`). It never closes that client and never mutates it.

- `manager.client` — the wrapped PyMongo client, unchanged.
- `manager.cache_core` — the manager's cache storage and bookkeeping object; see [Observability](#observability)
  below.
- `manager.close()` (`await manager.close()` for asyncio) — stops every change stream the manager opened and
  releases cached data. Does not close `manager.client`.
- `CacheManager` is also a context manager (`with` / `async with`), calling `close()` on exit.

Close the manager (or use it as a context manager) whenever you close the client it wraps. A manager starts a
background change-stream task the first time a read touches a database; leaving the manager open after closing the
client leaves that task running against a closed connection.

## Accessing databases and collections

```python
collection = manager["my_database"]["my_collection"]
```

`manager[name]` returns a `CachedDatabase`; `database[name]` returns a `CachedCollection`. Both are lightweight
views constructed on each access — they carry no state of their own beyond a reference to the manager and the
wrapped PyMongo object.

- `CachedDatabase.name`, `CachedCollection.name` — the wrapped object's name.
- `CachedDatabase.raw`, `CachedCollection.raw` — the wrapped PyMongo `Database`/`Collection`; see
  [Raw fallback](#raw-fallback).
- `CachedDatabase.manager` — the owning `CacheManager`.
- `CachedCollection.database` — the owning `CachedDatabase`.

## Cached read methods

`CachedCollection` exposes six read methods with the same names and signatures as their PyMongo equivalents:
`find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, and `distinct`. Each either returns a
cached result, admits a fresh result to the cache, or transparently bypasses to a direct PyMongo call — see
[Bypass conditions](#bypass-conditions) below for what decides which of the three happens. Two methods have a
narrower contract than their PyMongo counterparts:

- `find()` always returns a fully materialized `list`, not a cursor, and raises `UnsupportedCacheRequestError` if
  called with an option that only makes sense for a cursor (`cursor_type` other than `NON_TAILABLE`, or
  `allow_partial_results=True`). Use `collection.raw.find(...)` for a tailable, exhaust, or partial-result cursor.
- `aggregate()` also always fully materializes its result and raises `UnsupportedCacheRequestError` if the pipeline
  contains a `$changeStream` stage, since that cursor has no natural end to materialize toward. Use
  `collection.raw.aggregate(...)` for a change-stream pipeline.

Every other PyMongo collection or database method — all writes, and every read method not listed above
(`find_one_and_update`, `find_raw_batches`, index management, and so on) — is directly callable on the facade: an
attribute the facade doesn't itself define (for example `collection.insert_one(...)` or `database.create_collection(...)`)
delegates unmodified to the wrapped PyMongo object, the same object `.raw` returns. Whether a given method is one of
the six above — and therefore cached — is answered by this list, not by whether the facade lets you call it.

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
- A `find`, `count_documents`, or `distinct` filter is nondeterministic.
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

manager = CacheManager(
    client, cache_config=CacheCoreConfig(shared_budget_bytes=128 * 1024 * 1024)
)
```

| Field                       | Default   | Meaning                                                                                                                                                                                                                                                                          |
| --------------------------- | --------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `shared_budget_bytes`       | 64 MiB    | Total BSON-encoded size the manager's cache may hold at once, shared across every database and collection that manager caches.                                                                                                                                                   |
| `max_entry_bytes`           | 1 MiB     | The largest single cached value (one document, or one `find`/`aggregate`/`distinct` result) the cache accepts.                                                                                                                                                                   |
| `lag_capture_window_config` | see below | Sizes the invalidation-lag sample windows used by the stream-cost telemetry described in [Observability](#observability). Most applications never need to change this; it exists for the benchmark suite documented in [`stream-cost-benchmarks.md`](stream-cost-benchmarks.md). |

`CacheCoreConfig` raises `CacheConfigurationError` if `shared_budget_bytes` or `max_entry_bytes` is not positive, or
if `max_entry_bytes` exceeds `shared_budget_bytes`.

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

- `collection.raw` — the wrapped `pymongo.Collection` (or its asyncio equivalent).
- `database.raw` — the wrapped `pymongo.Database`.
- `manager.client` — the wrapped `pymongo.MongoClient` (or `AsyncMongoClient`).

Writes and every other non-cached method don't need `.raw` — call them directly on the facade (`collection.insert_one(...)`,
`database.create_collection(...)`); the facade delegates to the same wrapped object `.raw` returns, so the two forms are
interchangeable in behavior. `.raw` remains necessary for one narrower purpose: reaching PyMongo's own semantics for the
six cache-aware methods themselves — `find()` with a tailable, exhaust, or partial-result cursor, or `aggregate()` with a
`$changeStream` pipeline — since calling `find`/`aggregate` directly on the facade always goes through the cache-aware
override, which rejects those options with `UnsupportedCacheRequestError`.

`.raw` also keeps one advantage direct calls don't have: because it's typed as the concrete PyMongo `Collection`/`Database`,
mypy checks a `.raw` call's arguments and return type against PyMongo's real signature. A direct call on the facade for a
method the facade doesn't override type-checks but without that argument/return validation, since the facade can't know in
advance which PyMongo method a caller will reach for. Prefer `.raw` for a write or admin call where you want full static
checking; either form behaves identically at runtime.

## Rollback to plain PyMongo

Because `CacheManager` wraps a client you already own rather than replacing it, removing the cache layer is a
mechanical change, not a migration: replace `manager["db"]["collection"]` calls with `client["db"]["collection"]`
(PyMongo's own object). No other application code needs to change — a `CachedCollection`/`CachedDatabase` delegates
every method it doesn't cache to the same wrapped object `client["db"]["collection"]` already is, so a write or admin
call written directly against the facade (`collection.insert_one(...)`) keeps working unchanged once the facade is
gone entirely. No data migration is needed either — the manager never alters stored documents, it only caches read
results in your process's memory.

## Errors

| Exception                      | Raised when                                                                                                                   | What to do                                                           |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| `CacheConfigurationError`      | A `CacheCoreConfig` value is invalid (non-positive, or `max_entry_bytes` exceeds `shared_budget_bytes`).                      | Fix the configuration value.                                         |
| `CacheClosedError`             | A cached read is attempted after `manager.close()`.                                                                           | Don't use a manager (or a facade obtained from it) after closing it. |
| `UnsupportedCacheRequestError` | `find()` is called with a tailable/exhaust/partial-result option, or `aggregate()` is called with a `$changeStream` pipeline. | Use `.raw` for that call.                                            |

Every other unsupported or ambiguous condition — an incompatible read preference or read concern, a session-bound
read, a nondeterministic filter or pipeline, a view, a time-series collection, an oversized result, a database whose
change stream isn't healthy or can't be established — bypasses the cache and returns a normal PyMongo result instead
of raising. See [`docs/architecture.md`](architecture.md#retry-and-error-handling) for stream-level failures, which
are retried internally rather than surfaced to callers at all.
