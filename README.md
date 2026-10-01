# client-query-cache

Client-side caching for PyMongo, kept coherent using MongoDB change streams. For Python applications that already talk to MongoDB through PyMongo directly, it adds a coherent read cache without introducing a separate cache server or changing how you connect. The library supports synchronous and asyncio clients.

It caches reads whose results the manager can invalidate correctly when the underlying data changes, and leaves everything else — including all writes — to go straight to MongoDB. Invalidation is asynchronous: a read running concurrently with a write can still return the previous cached value until the manager processes that write's change-stream event.

**Built for production:** 100% covered, extensively tested from cache-core invariants through real MongoDB deployments, continuously benchmarked, and protected by an automated pull-request performance regression guard.

![Cached reads are up to about 1,200 times faster than a direct read, and roughly the same speed whether the server is local or a real remote deployment. Direct local server read 120 microseconds, direct real deployment (Atlas M0 free tier) read 79.4 milliseconds, cached read about 61 microseconds either way. Bars use a logarithmic scale.](docs/assets/benchmark-latency-light.svg)

Read latency across two different deployments, so you can see the range: the local-server row is the median from one of the [retained local benchmark reports](docs/stream-cost-benchmarks.md); the M0-deployment row is the mean of one batch from the [real-server benchmark](CONTRIBUTING.md#real-server-benchmark) against a free-tier Atlas (M0) cluster — plotted on a logarithmic axis given the size of the gap. Cached-read latency barely moves between the two, since a cache hit never touches the network. Neither number is a universal performance guarantee for your own workload or deployment — see [Stream cost benchmarks](docs/stream-cost-benchmarks.md) for the full local workload matrix and how to reproduce it.

---

## Requirements

`client-query-cache` requires Python 3.14.6 or newer.

Reads and writes work against any MongoDB deployment PyMongo supports. **Effective caching** needs two separate things: a replica set or sharded cluster, since MongoDB only provides change streams on one of those topologies, not a standalone server; and MongoDB 8.0 or newer, a floor this library enforces itself at startup rather than a limit of change streams themselves. Against a deployment that doesn't meet both, the manager doesn't raise: it logs a warning and bypasses the cache for that database, executing every read as a normal, uncached PyMongo call.

## Install

```bash
uv add client-query-cache
```

Or with pip: `pip install client-query-cache`.

## Usage

`CacheManager` wraps a `pymongo.MongoClient` (or `pymongo.AsyncMongoClient`) that you construct and own. Keep using your PyMongo collection for writes and everything else, and ask the manager for a cached view of that collection for six reads — `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, and `distinct`. The cache keeps those results coherent as the underlying data changes:

```python
from pymongo import MongoClient

from client_query_cache import CacheManager

with (
    MongoClient("mongodb://localhost:27017") as client,
    CacheManager(client) as cache_manager,
):
    collection = client["my_database"]["my_collection"]
    cached_collection = cache_manager.cached(collection)

    collection.insert_one({"_id": "example", "value": 42})

    # Cache miss: reads from MongoDB.
    cached_collection.find_one({"_id": "example"})
    # Cache hit: served from the cache.
    cached_collection.find_one({"_id": "example"})

    # Prints 1. Bridge stats like this into OpenTelemetry:
    # docs/architecture.md#opentelemetry-metrics
    print(cache_manager.cache_core.snapshot().hits)

    collection.create_index("email", unique=True)
    collection.insert_one({"_id": "user-1", "email": "a@example.com"})
    # Also cached, like an `_id` lookup.
    cached_collection.find_one({"email": "a@example.com"})
```

`collection` is PyMongo's own object, so your editor and type checker see PyMongo's real methods and signatures. `cached_collection` has only the six cached reads; `find` and `aggregate` on it return a list instead of a cursor. Use `cached_collection.raw` (the same `collection`) whenever you need PyMongo's own cursor behavior.

`find_one` caches deterministic single-document queries, including compound filters, match-all reads and missing results. Use `sort` to choose the first matching document and `collation` to control string matching:

```python
cached_collection.find_one(
    {"status": "active"},
    sort=[("updated_at", -1)],
    collation={"locale": "en", "strength": 2},
)
```

Exact `_id` lookups and qualifying unique indexes allow cached reads to survive writes to other documents. Other queries are refreshed after any write to the collection. Updates become visible after the manager processes their change-stream events. To make cached reads reflect a write you just made, capture the write's session position and wait for it with `cache_manager.wait_for_invalidations()` (see [Waiting for your own writes](docs/api-reference.md#waiting-for-your-own-writes)), or read through the PyMongo collection.

`CacheManager` starts a background change-stream task the first time a read touches a database, so close it (or use it as a context manager, as above) alongside the client — closing only the client leaves that background task running against a closed connection.

The same API is available for `pymongo.AsyncMongoClient` under `client_query_cache.asynchronous`, with the cached reads as coroutines:

```python
import asyncio

from pymongo import AsyncMongoClient

from client_query_cache.asynchronous import CacheManager


async def main() -> None:
    async with (
        AsyncMongoClient("mongodb://localhost:27017") as client,
        CacheManager(client) as cache_manager,
    ):
        collection = client["my_database"]["my_collection"]
        cached_collection = cache_manager.cached(collection)

        await collection.insert_one({"_id": "example", "value": 42})

        # Cache miss.
        await cached_collection.find_one({"_id": "example"})
        # Cache hit.
        await cached_collection.find_one({"_id": "example"})
        # A list, not a cursor.
        await cached_collection.find({"value": 42})


asyncio.run(main())
```

A read bypasses the cache instead of using it whenever caching it safely isn't possible — for example, a caller-selected session, read preference, or read concern; a view; a nondeterministic or cross-collection aggregation pipeline; a time-series collection; or a database whose change stream isn't healthy. See [Bypass conditions](docs/api-reference.md#bypass-conditions) in the API reference for the complete list.

## Scope and constraints

- **Writes aren't cached** — only the six read methods listed above are. See [why only reads are cached](docs/architecture.md#why-only-reads-are-cached) for the rationale.
- **Each `CacheManager` is independent** — it owns its own in-process cache and its own change-stream cursors; nothing is shared between managers or processes. See [capacity planning](docs/architecture.md#capacity-estimation) before creating one per request or one per worker process.

## Documentation

- [API reference](docs/api-reference.md) — the complete public surface: construction, configuration, limits, ownership, and raw fallback.
- [Architecture and operations](docs/architecture.md) — system requirements, capacity planning, retry/error handling, observability, security, and recovery behavior.
- [Examples](examples/README.md) — runnable programs that add the cache to real libraries that store data in MongoDB, such as requests-cache.
- [Stream cost benchmarks](docs/stream-cost-benchmarks.md) — whether caching fits your workload, and the controlled benchmark reports backing that guidance.

---

> MongoDB is a registered trademark of MongoDB, Inc. This project is independent and is not affiliated with, sponsored by, or endorsed by MongoDB, Inc.
