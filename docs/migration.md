# Recovering from the prototype

This is a pre-release, single-maintainer project with no external users, so there is no real migration to perform — this page just records the boundary between the abandoned proof of concept and the supported API, for whoever (including future-you) reads the history.

## Retained

| Prototype                                                    | Current                                                                                                  |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------- |
| `mongo_client_cache.synchronous.database.CachedDatabase`     | Same name, same module, now composed instead of subclassing `pymongo.synchronous.database.Database`.     |
| `mongo_client_cache.synchronous.collection.CachedCollection` | Same name, same module, now composed instead of subclassing `pymongo.synchronous.collection.Collection`. |

## Replaced

| Prototype                                                                                                                  | Current                                                                                     |
| -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `CachedMongoClient(uri, cache_config={...})`, which subclassed `pymongo.MongoClient` and owned the connection itself       | `CacheManager(client)`, which wraps a `pymongo.MongoClient` you construct and own yourself. |
| `ClientSideCacheConfig` / `CollectionConfig(watch_change_stream=...)`, an upfront per-database/per-collection registration | `manager[database_name][collection_name]`, built on demand — no upfront registration.       |

## Removed (no replacement yet)

Everything below implemented client-side caching: read caching, write-then-wait-for-change-stream coherency, and the busy-poll wait loop that caused flaky change-stream timeouts under load. None of it survived the recovery. It returns incrementally in later changes (`implement-cache-core`, `implement-change-stream-coherency`, `implement-cached-read-api`) with a different, bounded design.

- `mongo_client_cache.synchronous.cursor.CachedCursor` and all cached-read behavior on `find`, `find_one`, `count_documents`, `estimated_document_count`, `distinct`.
- The `mongo_client_cache.cache` package (`CollCache`, the change-stream pipeline, the cache-key commands, and the cache exceptions).
- Write interception on `insert_one`, `insert_many`, `delete_one`, `delete_many` (waiting for the change stream), and the `CannotEditImmutableCollectionError` guard on `update_one`, `update_many`, `replace_one`, `find_one_and_*`, `drop`, `rename`.
- `mongo_client_cache._misc.dt_now`, `mongo_client_cache.logger`, and the cache-only types in `mongo_client_cache._types`.

## Using raw PyMongo today

Nothing is cached yet. Every facade exposes `.raw`, the exact PyMongo object it wraps, so you can call any collection or database method PyMongo supports:

```python
from pymongo import MongoClient

from mongo_client_cache import CacheManager

with MongoClient("mongodb://localhost:27017") as client:
    manager = CacheManager(client)
    collection = manager["my_database"]["my_collection"]
    collection.raw.insert_one({"_id": "example", "value": 42})
    document = collection.raw.find_one({"_id": "example"})
```

You can also skip the manager entirely for collections you have not wrapped yet — `client["my_database"]["other_collection"]` keeps behaving exactly like plain PyMongo, so adopting `CacheManager` for one collection at a time never changes the others. This example is exercised by `tests/e2e/test_installed_package.py` against an installed build of the package.

The same seam exists for `pymongo.AsyncMongoClient` under `mongo_client_cache.asynchronous` (`CacheManager`, `CachedDatabase`, `CachedCollection`), with the identical `.raw` escape hatch.
