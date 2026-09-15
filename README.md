# mongodb-client-cache

A high-performance, process-local caching layer for PyMongo (sync and asyncio), designed to invalidate cached reads via MongoDB change streams rather than relying primarily on time-based expiry.

The project targets realistic mixed workloads, including collections that rarely change alongside collections with frequent writes. Its intended design is to cache only operations whose results can be kept coherent safely and predictably, while falling back to direct MongoDB access for unsupported or ambiguous cases.

Writes are expected to participate in cache coherence, typically by invalidating affected cached entries; populating the cache from writes should occur only when the authoritative post-write document is available or when explicitly supported. MongoDB views and other operations whose invalidation semantics cannot be determined safely should bypass caching unless dedicated support is implemented.

---

## Status

`CacheManager` wraps a `pymongo.MongoClient` (or `pymongo.AsyncMongoClient`) that you construct and own. Its database and collection facades cache a narrow set of PyMongo's own read methods — `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, and `distinct` — and keep cached results coherent as the underlying data changes. Every other operation, including all writes, remains available through the wrapped PyMongo object via `.raw`:

```python
from pymongo import MongoClient

from mongo_client_cache import CacheManager

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

The same facades are available for `pymongo.AsyncMongoClient` under `mongo_client_cache.asynchronous`, with the same methods as coroutines.

A read bypasses the cache — falling back to a normal PyMongo call — whenever caching it safely isn't possible: when the caller supplies a session, a read preference other than primary, or a read concern other than majority; when the collection is a MongoDB view; when an aggregation pipeline joins another collection, writes, reports live statistics, or is otherwise nondeterministic; or when a `find`/`count_documents`/`distinct` filter is nondeterministic. `find()` always returns a fully materialized list rather than a cursor, so it does not support a tailable, exhaust, or partial-result read — use `collection.raw.find(...)` for those.

Leaving read concern unspecified (the common case) is treated as compatible with caching, not as a bypass condition: a cache miss reads at majority concern, which is stronger, and can be slower or less available during a network partition, than the server's own default read concern an uncached call would otherwise use.

See [`docs/migration.md`](docs/migration.md) for what changed since the earlier prototype.
