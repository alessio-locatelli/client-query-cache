# Synchronous quick start

This program writes a document to your local MongoDB replica set and reads it through a cached view. It uses a dedicated tutorial collection.

```python
from pymongo import MongoClient

from client_query_cache import CacheManager

with (
    MongoClient("mongodb://localhost:27017") as client,
    CacheManager(client) as cache_manager,
):
    collection = client["client_query_cache_tutorial"]["items"]
    cached_collection = cache_manager.get_cached_collection(collection)

    collection.replace_one(
        {"_id": "example"}, {"_id": "example", "value": 42}, upsert=True
    )

    first = cached_collection.find_one({"_id": "example"})
    repeated = cached_collection.find_one({"_id": "example"})
    print(first, repeated)
    print("Cache hits:", cache_manager.snapshot().hits)

    items = list(cached_collection.find({"value": 42}))
    print(items)
```

Save the program as `quick_start.py` and run `python quick_start.py` in the environment where you installed the library. On an eligible deployment with a healthy stream, repeated reads can hit the cache. If caching is unavailable, both reads execute through PyMongo; [monitoring](../operations/monitoring.md) explains how to inspect bypasses. Startup and concurrent changes can affect the observed hit count.

Keep the PyMongo `collection` for writes and administration. The cached view exposes [six read methods](../usage/cached-reads.md); `find` and `aggregate` return cursors. Iterate them or use `list(cursor)` / `cursor.to_list()` to materialize their documents. Use `.raw` when a read must execute against MongoDB.

The context managers close the cache manager before the client. A manager never closes your client, and closing only the client leaves the manager's background task running. Reuse a long-lived manager across application requests; see [deployment](../operations/deployment.md#capacity-estimation).

A cached read after a write can still see an earlier value until invalidation arrives. Use a direct PyMongo read where freshness is required, with the appropriate session and concerns; see [consistency](../usage/consistency.md). Eligible cache misses read from the primary with `majority` read concern even though this program leaves read concern unspecified, so they can differ from a direct read that uses the deployment's default, normally `local`; see [bypass conditions](../reference/api.md#bypass-conditions).
