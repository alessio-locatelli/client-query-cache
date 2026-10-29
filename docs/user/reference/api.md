# API reference

This reference describes `CacheManager` and its cached views. For `SharedCacheServer`, `SharedCacheManager` and shared configuration, use the [shared API reference](shared-cache.md). Start with [manager selection](../getting-started/choose-a-manager.md), then the [synchronous](../getting-started/synchronous.md) or [asyncio](../getting-started/asyncio.md) tutorial.

Synchronous names live at the top level (`client_query_cache`) and wrap `pymongo.MongoClient`. Their asyncio counterparts live under `client_query_cache.asynchronous` and wrap `pymongo.AsyncMongoClient`. In this page, “both APIs” means those two process-local variants. Await single-result reads and `aggregate()` with asyncio; `find()` returns its async cursor immediately.

## Constructing a manager

```python
from client_query_cache import CacheManager

cache_manager = CacheManager(client)
```

`CacheManager(client, *, cache_config=None, max_await_time_ms=1_000)` wraps a caller-constructed and caller-owned `MongoClient` (or
`AsyncMongoClient`). It never closes that client and never mutates it.

- `cache_manager.client` — the wrapped PyMongo client, unchanged.
- `cache_manager.cache_core` — the manager's cache storage and bookkeeping object; see [Observability](../operations/monitoring.md#observability).
- `cache_manager.get_cached_collection(collection)` — a cached read view of one of your PyMongo collections; see [Cached collection views](#cached-collection-views).
- `cache_manager.close()` (`await cache_manager.close()` for asyncio) — stops every change stream the manager opened and releases cached data. Does not close `cache_manager.client`.
- `CacheManager` is also a context manager (`with` / `async with`), calling `close()` on exit.

Close the manager (or use it as a context manager) whenever you close the client it wraps. A manager starts a
background change-stream task the first time a read touches a database; leaving the manager open after closing the
client leaves that task running against a closed connection.

## Cached collection views

Keep two handles for a collection: PyMongo's own collection for writes, administration, and any read you don't want cached, and a cached view of it for the six cached reads.

```python
collection = client["my_database"]["my_collection"]
cached_collection = cache_manager.get_cached_collection(collection)

collection.insert_one({"_id": "example", "value": 42})
cached_collection.find_one({"_id": "example"})
```

The asyncio version is identical except that both calls are awaited:

```python
collection = client["my_database"]["my_collection"]
cached_collection = cache_manager.get_cached_collection(collection)

await collection.insert_one({"_id": "example", "value": 42})
await cached_collection.find_one({"_id": "example"})
```

The cached read does not wait for the insert's invalidation: if an earlier read cached the lookup, including a missing result, `find_one()` can still return that result until the manager processes the write's change-stream event. See [read after write](../usage/consistency.md#read-after-write).

`cache_manager.get_cached_collection(collection)` returns a `CachedCollection` whose `.raw` is exactly the collection you passed, including options you chose with `get_collection(...)` or `with_options(...)` — those options decide whether a read can use the cache (see [Bypass conditions](#bypass-conditions)). The collection must come from the manager's own client; a collection from any other client raises `ValueError`.

Calling `get_cached_collection(collection)` more than once is safe and cheap: every view from one manager shares that manager's cache and its single change stream per database, so a result cached through one view is a hit through another. Each call may return a new view object, so don't rely on two views being the same object; keep one around when convenient.

`cache_manager[name]` returns a `CachedDatabase`, and `database[name]` returns a `CachedCollection`, as a shorthand for cached reads when you don't already hold a PyMongo collection. Attribute access (`database.users`, `cached_collection.chunks`) also returns a cached view of that collection or sub-collection. Index access always works, including for a collection named like a PyMongo method (`database["create_collection"]`).

- `CachedDatabase.name`, `CachedCollection.name` — the wrapped object's name.
- `CachedDatabase.raw`, `CachedCollection.raw` — the wrapped PyMongo `Database`/`Collection`; see [Raw fallback](#raw-fallback).
- `CachedDatabase.manager` — the owning `CacheManager`.
- `CachedCollection.database` — the owning `CachedDatabase`.

Cached views expose nothing else. PyMongo methods such as `insert_one`, `create_index`, `drop`, `with_options`, or `create_collection` raise `AttributeError` on a view — call them on your PyMongo object or on `.raw`.

## Cached read methods

`CachedCollection` provides six cached reads. Eligible reads can reuse cached results; ineligible reads execute through PyMongo. Cached views remain read-only: writes and other methods belong on the PyMongo collection or `.raw`.

| Method                     | Synchronous result | Asyncio call                                   | Cache lookup and execution                                                  |
| -------------------------- | ------------------ | ---------------------------------------------- | --------------------------------------------------------------------------- |
| `find_one`                 | Document or `None` | Awaited                                        | During the call                                                             |
| `find`                     | `Cursor` subclass  | Not awaited; returns an `AsyncCursor` subclass | When consumption starts                                                     |
| `aggregate`                | `CommandCursor`    | Awaited; returns an `AsyncCommandCursor`       | During the call; a miss or bypass runs the initial command before returning |
| `count_documents`          | `int`              | Awaited                                        | During the call                                                             |
| `estimated_document_count` | `int`              | Awaited                                        | During the call                                                             |
| `distinct`                 | `list`             | Awaited                                        | During the call                                                             |

`find()` construction validates arguments locally and performs no database read or cache lookup.

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

In both APIs, `find()` shares cached results across top-level permutations of
ordinary scalar equality predicates in plain dictionaries. Values must be
`None` or exact built-in bool, int, float, or str instances, with exact built-in string field
names not starting with `$`. Other options and value types remain distinct.
Document/array values, operators, regexes, BSON-specific scalars, and custom
forms retain ordered matching and their existing eligibility. Native execution
receives the original filter. Other read methods do not gain this rule. See the
[scalar equality example](../usage/cached-reads.md#filters-sorting-and-collation).

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

`find_one()` filters that pin `_id` to an exact value under simple collation, alone or with additional
predicates, and qualifying unique-index `find_one()` reads can retain a cached result after writes to other
documents. For example, `cached_collection.find_one({"_id": order_id, "customer_id": customer_id})`
keeps its cached result when another order changes. Partial, sparse and hashed indexes do not qualify for this optimization.
Unique-index collation must have a confirmed match: inherited defaults and fully specified explicit matches
qualify; an explicit collation with omitted defaults may use collection-wide invalidation instead.
Other eligible single-document queries are refreshed after any write to the collection, including writes
that could introduce a match for a cached missing result. Every `find()`, `aggregate()`,
`count_documents()`, `distinct()` and `estimated_document_count()` result is also refreshed after any
write to the collection.

Cache invalidation is eventual. A cached read can return its previous value until the manager processes
the relevant change-stream event. Use the PyMongo collection or a session-bound read when you need to
immediately observe a preceding write. Additional keyword options execute directly through PyMongo;
malformed arguments preserve the driver's errors.

## Bypass conditions

A read bypasses the cache — executing as a normal PyMongo call instead of a lookup or admission — whenever caching
it safely isn't possible:

- The caller supplies a session or uses `session.bind()`, a read preference other than primary, or a read concern other than majority. Leaving read concern unspecified (the common case) does not bypass caching: an eligible miss reads from the primary with [`majority` read concern](https://www.mongodb.com/docs/manual/reference/read-concern-majority/), while an uncached read uses the deployment's [default read concern](https://www.mongodb.com/docs/manual/reference/mongodb-defaults/), normally `local`. Majority reads usually perform comparably, but they return only writes acknowledged by a majority of replica set members. While replication lags or no majority commit point is available, a miss can therefore return older data than a `local` read, or fail where a `local` read would succeed. Majority reads keep writes that could later roll back out of the cache; they do not make hits current, because [invalidation](../usage/consistency.md) remains asynchronous.
- Find cursor-only requests (tailable, exhaust, partial results), explicit find batching, unsupported find options, and aggregation batching supplied at invocation execute natively. `$changeStream` pipelines also execute natively without caching.
- Pipelines that use MongoDB Search or Vector Search, or list search indexes (`$search`, `$searchMeta`, `$vectorSearch`, `$listSearchIndexes`), run through PyMongo with the caller's read concern and are never cached.
- The collection is a MongoDB view.
- An aggregation pipeline joins another collection, writes, reports live statistics, or is otherwise
  nondeterministic (for example a `$sample` stage or a `$rand` expression).
- A `find_one`, `find`, `count_documents`, or `distinct` filter is nondeterministic.
- A read depends on indexes or on the caller's roles: `$text` and geospatial proximity (`$near`, `$nearSphere`, `$geoNear`) queries, and filters, projections, or pipelines that reference `$$USER_ROLES`. Index creation and deletion refresh cached query results, but index visibility changes and changes to a user's roles do not.
- A `find_one` or `find` projection uses `$meta`, or computes a changing value with `$rand`, `$function`, `$$NOW`, or `$$CLUSTER_TIME`.
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
    client, cache_config=CacheCoreConfig(budget_bytes=128 * 1024 * 1024)
)
```

| Field                       | Default                  | Meaning                                                                                                                                                                                                                                                                                                   |
| --------------------------- | ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `budget_bytes`              | 64 MiB                   | Total BSON-encoded size the manager's cache may hold at once, shared across every database and collection that manager caches.                                                                                                                                                                            |
| `max_entry_bytes`           | 1 MiB                    | The largest single cached value (one document, or one `find`/`aggregate`/`distinct` result) the cache accepts.                                                                                                                                                                                            |
| `max_entries`               | `None`                   | Optional manager-wide limit on resident values plus unique-key aliases.                                                                                                                                                                                                                                   |
| `max_key_bytes`             | `None`                   | Optional maximum accounted key size for each retained value or alias.                                                                                                                                                                                                                                     |
| `max_namespaces`            | 1,024                    | Maximum number of database/collection pairs whose cache state the manager tracks at once. A dropped collection releases its slot; other names bypass caching while all slots are in use.                                                                                                                  |
| `lag_capture_window_config` | 10 windows of 100 events | Sizes the invalidation-lag sample windows used by the stream-cost telemetry described in [Observability](../operations/monitoring.md#observability). Most applications never need to change this; it exists for the benchmark suite documented in [stream cost benchmarks](../benchmarks/stream-cost.md). |

`budget_bytes` and `max_entry_bytes` must be positive, and `max_entry_bytes` must not exceed
`budget_bytes`. `max_namespaces` must be positive. Equal budgets are allowed.

The `lag_capture_window_config` has three numeric fields: `window_count` and `events_per_window` must be
positive; `min_separation_events` must be nonnegative. The default separation is zero, allowing adjacent windows.

Numeric fields require exact built-in integers; `max_entries` and `max_key_bytes` also accept `None` to disable their checks and otherwise must be positive. Booleans, integer subclasses, floats (including NaN and
infinities), strings, and other types raise `CacheConfigurationError` at configuration construction,
naming the invalid field. Values are not converted. Invalid ranges or budget relationships also raise
`CacheConfigurationError` at construction.

### Change-stream await time

Set `max_await_time_ms` on the synchronous or asyncio `CacheManager` to choose the maximum idle server wait for a change-stream batch:

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
- Cursor candidates also cap their retained encoded payload at `max_entry_bytes`; exceeding it discards the candidate while native delivery continues. Native batches, decoded hit snapshots, wrappers, and temporary encoding allocations consume additional memory. This is not a process-memory limit; see [memory beyond the cache budget](../operations/deployment.md#memory-beyond-the-cache-budget).
- Once the cache's total stored BSON size would exceed `budget_bytes`, admitting a new entry evicts the
  least-recently-used entries to make room. Query keys and Python metadata consume additional memory outside
  this budget, especially for large predicates with small results; see
  [memory beyond the cache budget](../operations/deployment.md#memory-beyond-the-cache-budget) for measured examples.
- A read whose `_id` or result depends on a value that cannot be used as a cache key — for example a `bson.Code`
  value, or a `NaN`, which is never equal to itself — is executed and returned normally without being cached.

Admission limits preserve native results and cursor delivery without adding read-time exceptions. The cache may evict older entries or decline a value or alias while retaining other eligible entries. See [deployment guidance](../operations/deployment.md#capacity-estimation) for how to size these limits against your deployment.

### Optional retention limits

`max_entries` counts resident values and unique-key aliases together across every collection in one manager. When a value needs space, the cache first reclaims old aliases, then evicts least-recently-used values. Removing an alias leaves its value eligible for direct identity reads. An alias whose value was evicted can remain while an in-flight identity read holds its relationship; it still consumes a slot.

For a unique-key read with the count limit enabled, the cache prefers one identity value and its alias, avoiding a second value record and BSON-budget charge. With one available slot it retains the original query result instead, so repeated queries can hit. With two available slots it can retain the pair, supporting both unique-key and identity reads. If a two-slot cache already holds two unrelated values, a new unique-key read can replace the oldest value with its original query result; it does not evict the second value merely to obtain an alias. Existing records, replacements, BSON capacity and key eligibility also affect this choice. Setting only `max_key_bytes` keeps the ordinary admission policy.

`max_key_bytes` measures a key independently for each candidate value or alias. It sums shallow Python object sizes, visits tuple contents, and counts each object identity once per record. Query results use their canonical query key; identity results include identity and read shape; aliases include the alias key and resolved identity. Shared namespace identifiers and canonical tags are excluded. Equality with the limit is allowed. A key that exceeds the limit, or whose size cannot be obtained, is declined without raising a sizing error to the caller. An independently declined alias can accompany a successfully admitted value.

This charge excludes objects reachable through opaque scalar values, cache indexes and allocator overhead. Neither optional limit bounds in-flight requests, decoded results held by callers, or RSS. Sizing runs for candidate publication, not cache hits. [Deployment guidance](../operations/deployment.md#capacity-estimation) shows an opt-in configuration.

## Ownership

Create the client and manager inside the process that uses them, and reuse them across requests. The manager owns cached data and one change stream per active database. Close it before closing its caller-owned client, using `with` or `async with` where practical.

Each process-local manager has an independent budget and streams, even when another manager uses the same client or deployment. Use [shared managers](shared-cache.md) for that deployment.

Advanced direct construction of exported cache-core and coordinator types is covered by the [maintainer architecture reference](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/architecture.md#low-level-design). Do not share one core between multiple coordinators.

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

| Exception                      | Raised when                                                                                                                  | What to do                                                         |
| ------------------------------ | ---------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `CacheConfigurationError`      | A cache budget, lag-window field, the manager's `max_await_time_ms`, or an OpenTelemetry `lag_percentiles` value is invalid. | Fix the configuration value.                                       |
| `CacheClosedError`             | A cached read is attempted after `cache_manager.close()`.                                                                    | Don't use a manager (or a view obtained from it) after closing it. |
| `UnsupportedCacheRequestError` | An explicit low-level cache operation receives an unsupported key value.                                                     | Use a supported key or the native collection.                      |
| `ValueError`                   | `cache_manager.get_cached_collection(collection)` receives a collection from a different client.                             | Pass a collection from `cache_manager.client`.                     |

Every other unsupported or ambiguous condition — a tailable, exhaust, or partial-result `find()`, a `$changeStream` aggregation, an incompatible read preference or read concern, a session-bound
read, a nondeterministic filter or pipeline, a view, a time-series collection, an oversized result, a database whose
change stream isn't healthy or can't be established — bypasses the cache and returns a normal PyMongo result instead
of raising. See [deployment guidance](../operations/deployment.md#retry-and-error-handling) for stream-level failures, which
are retried internally rather than surfaced to callers at all.

## Diagnostics

Both process-local variants provide synchronous, read-only local inspection, including after close:

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

`CacheSnapshot.entry_count` counts resident values, `alias_count` counts retained aliases, and `used_bytes` counts BSON bytes. `budget_bytes`, `max_entries` and `max_key_bytes` expose the configured capacities. After close, resident value and alias counts are zero.

`retention_declines` is a fixed tuple of `RetentionDeclineCount(kind, reason, count)` records. Kinds are `namespace_value`, `identity_value` and `alias`; reasons are `key_size_limit`, `key_size_unavailable` and `entry_capacity`. Counters measure declined publications, rather than reads. A failed unique-key pair records its first blocking candidate (identity before alias); a failed namespace fallback adds its own key decline. Retries do not add duplicate events. A successful fallback can therefore have one retention decline. These counters do not change `bypasses`, `oversized_bypasses`, or their OpenTelemetry series; they have no separate OpenTelemetry instruments.

`RetentionDeclineCount`, `RetentionRecordKind`, `RetentionDeclineReason`, `CacheSnapshot`, `BypassReason`, `BypassReasonCount`, `StreamCostSnapshot`, `StreamHealthSnapshot`, and
`StreamHealthStatus` are importable from `client_query_cache`, `client_query_cache.synchronous`, and
`client_query_cache.asynchronous`. See [bypass reasons and stream health](../operations/monitoring.md#bypass-reasons-and-stream-health)
for their meaning and limitations.
