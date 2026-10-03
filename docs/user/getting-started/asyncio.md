# Asyncio quick start

First [install the library](installation.md) and connect to MongoDB 8.0 or newer on a replica set or sharded cluster. Import the asyncio manager from `client_query_cache.asynchronous` and await its reads.

```python
import asyncio

from pymongo import AsyncMongoClient

from client_query_cache.asynchronous import CacheManager


async def main() -> None:
    async with (
        AsyncMongoClient("mongodb://localhost:27017") as client,
        CacheManager(client) as cache_manager,
    ):
        collection = client["client_query_cache_tutorial"]["items"]
        cached_collection = cache_manager.cached(collection)

        await collection.replace_one(
            {"_id": "example"}, {"_id": "example", "value": 42}, upsert=True
        )

        first = await cached_collection.find_one({"_id": "example"})
        repeated = await cached_collection.find_one({"_id": "example"})
        print(first, repeated)
        print("Cache hits:", cache_manager.snapshot().hits)

        items = await cached_collection.find({"value": 42})
        print(items)


asyncio.run(main())
```

Save the program as `quick_start_async.py` and run `python quick_start_async.py` in the environment where you installed the library. On an eligible deployment with a healthy stream, repeated reads can hit the cache. If caching is unavailable, reads bypass to PyMongo. Startup and concurrent changes can affect the observed hit count; inspect [bypass reasons and stream health](../operations/monitoring.md#bypass-reasons-and-stream-health) for diagnostics.

Use the PyMongo collection for writes. Awaiting `find` or `aggregate` on the cached view returns a list; use `.raw` when you need the driver's cursor semantics. See [cached reads](../usage/cached-reads.md).

The `async with` block closes the manager before the client. Outside a context manager, call `await cache_manager.close()` before `await client.close()`. The manager owns its background streams and cached data, and you own the client. Keep both alive across application requests; see [deployment](../operations/deployment.md).

Awaiting a cached read does not wait for a preceding write's invalidation. Use a direct PyMongo read with suitable session and concerns for freshness requirements; see [consistency](../usage/consistency.md).

Continue with [workload evaluation](../benchmarks/index.md), [integration examples](../examples/index.md), or the [API reference](../reference/api.md).
