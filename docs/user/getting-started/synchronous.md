# Synchronous quick start

First [install the library](installation.md) and connect to MongoDB 8.0 or newer on a replica set or sharded cluster. The program below uses your local deployment and a dedicated tutorial collection. It writes one document and reads it through a cached view.

```python
from pymongo import MongoClient

from client_query_cache import CacheManager

with (
    MongoClient("mongodb://localhost:27017") as client,
    CacheManager(client) as cache_manager,
):
    collection = client["client_query_cache_tutorial"]["items"]
    cached_collection = cache_manager.cached(collection)

    collection.replace_one(
        {"_id": "example"}, {"_id": "example", "value": 42}, upsert=True
    )

    first = cached_collection.find_one({"_id": "example"})
    repeated = cached_collection.find_one({"_id": "example"})
    print(first, repeated)
    print("Cache hits:", cache_manager.snapshot().hits)

    items = cached_collection.find({"value": 42})
    print(items)
```

Save the program as `quick_start.py` and run `python quick_start.py` in the environment where you installed the library. On an eligible deployment with a healthy stream, repeated reads can hit the cache. If caching is unavailable, both reads execute through PyMongo; [monitoring](../operations/monitoring.md) explains how to inspect bypasses. Startup and concurrent changes can affect the observed hit count.

Keep the PyMongo `collection` for writes and administration. The cached view exposes [six read methods](../usage/cached-reads.md); `find` and `aggregate` return lists. Use `cached_collection.raw` for PyMongo cursor behavior.

The context managers close the cache manager before the client. A manager never closes your client, and closing only the client leaves the manager's background task running. Reuse a long-lived manager across application requests; see [deployment](../operations/deployment.md#capacity-estimation).

A cached read after a write can still see an earlier value until invalidation arrives. Use a direct PyMongo read where freshness is required, with the appropriate session and concerns; see [consistency](../usage/consistency.md).

Continue with [cached reads](../usage/cached-reads.md), [workload evaluation](../benchmarks/index.md), or the [API reference](../reference/api.md).
