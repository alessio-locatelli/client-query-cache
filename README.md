# client-query-cache

Client-side caching for PyMongo, kept coherent using MongoDB change streams. For Python applications that already talk to MongoDB through PyMongo directly, it adds a coherent read cache without introducing a separate cache server or changing how you connect. The library supports synchronous and asyncio clients.

It caches only operations whose results can be kept coherent safely and predictably, and falls back to direct MongoDB access for every other case — including all writes, which always go straight to MongoDB through `.raw`. Once the manager processes the change-stream event a write produces, it invalidates every cached result the write could have affected, so the next read re-fetches instead of returning stale data.

![Bar chart: median read latency for a read-heavy workload with small documents — direct MongoDB read 120 microseconds versus cached read hit 61 microseconds, about 2 times faster](docs/assets/benchmark-latency-light.svg)

Median latency from one of the [retained benchmark reports](docs/stream-cost-benchmarks.md) — a local, single-node measurement for one workload, not a universal performance guarantee. See [Stream cost benchmarks](docs/stream-cost-benchmarks.md) for the full workload matrix and how to reproduce it.

---

## Requirements

`client-query-cache` requires Python 3.14.6 or newer and a MongoDB server version 8.0 or newer running as a replica set or sharded cluster — change streams, which this library relies on to invalidate cached data, aren't available against a standalone server. Against a server or topology that can't provide change streams, the manager doesn't raise: it logs a warning and every read for that database bypasses the cache instead of using it.

## Install

```bash
uv add client-query-cache
```

Or with pip: `pip install client-query-cache`.

## Usage

`CacheManager` wraps a `pymongo.MongoClient` (or `pymongo.AsyncMongoClient`) that you construct and own. Its database and collection facades cache a narrow set of PyMongo's own read methods — `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, and `distinct` — and keep cached results coherent as the underlying data changes. Every other operation, including all writes, remains available through the wrapped PyMongo object via `.raw`:

```python
from pymongo import MongoClient

from client_query_cache import CacheManager

with (
    MongoClient("mongodb://localhost:27017") as client,
    CacheManager(client) as manager,
):
    collection = manager["my_database"]["my_collection"]

    collection.raw.insert_one({"_id": "example", "value": 42})
    collection.find_one({"_id": "example"})  # cached, and invalidated by later writes

    collection.raw.create_index("email", unique=True)
    collection.raw.insert_one({"_id": "user-1", "email": "a@example.com"})
    collection.find_one({"email": "a@example.com"})  # also cached, like an `_id` lookup
```

`find_one` caches a lookup by `_id` and by any other field the database enforces as unique, discovered automatically from the collection's own indexes — there's nothing to declare. Only a plain unique index qualifies: a partial, sparse, or hashed unique index, or a read whose collation doesn't match the index's collation, falls back to an uncached read instead.

`CacheManager` starts a background change-stream task the first time a read touches a database, so close it (or use it as a context manager, as above) alongside the client — closing only the client leaves that background task running against a closed connection.

The same facades are available for `pymongo.AsyncMongoClient` under `client_query_cache.asynchronous`, with the same methods as coroutines.

A read bypasses the cache — falling back to a normal PyMongo call — whenever caching it safely isn't possible: when the caller supplies a session, a read preference other than primary, or a read concern other than majority; when the collection is a MongoDB view; when an aggregation pipeline joins another collection, writes, reports live statistics, or is otherwise nondeterministic; or when a `find`/`count_documents`/`distinct` filter is nondeterministic. `find()` always returns a fully materialized list rather than a cursor, so it does not support a tailable, exhaust, or partial-result read — use `collection.raw.find(...)` for those.

Leaving read concern unspecified (the common case) is treated as compatible with caching, not as a bypass condition: a cache miss reads at majority concern, which is stronger, and can be slower or less available during a network partition, than the server's own default read concern an uncached call would otherwise use.

Time-series collections bypass caching because MongoDB does not provide change streams for them. Reads of a collection that does not yet exist also bypass caching and recheck its type on later reads. A missing document in an existing ordinary collection can still be cached. If a time-series collection is replaced with an ordinary collection, reads may continue to bypass until a new manager is created when MongoDB supplies no notification that refreshes the collection type.

## Intentionally out of scope

**Writes aren't cached** — only the six read methods listed above are. See [why only reads are cached](docs/architecture.md#why-only-reads-are-cached) for the rationale.

## Documentation

- [API reference](docs/api-reference.md) — the complete public surface: construction, configuration, limits, ownership, and raw fallback.
- [Architecture and operations](docs/architecture.md) — system requirements, capacity planning, retry/error handling, observability, security, and recovery behavior.
- [Stream cost benchmarks](docs/stream-cost-benchmarks.md) — whether caching fits your workload, and the controlled benchmark reports backing that guidance.
