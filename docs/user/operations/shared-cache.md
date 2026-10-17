# Share a cache across application workers

Use `SharedCacheServer` when [trusted workers](#security-and-monitoring) on one host repeatedly make [eligible `_id` reads](../reference/shared-cache.md#worker-managers-and-reads). The server starts one cache-owner process; workers reuse its values and one change stream per active database. Sync and asyncio workers can share the same server. Each worker still owns a PyMongo client for misses, writes and uncached reads.

Compare [the two managers](../getting-started/choose-a-manager.md) before adopting this model. Sharing supports fewer cached operations and requires an application parent that stays alive until every worker has stopped.

## Supported deployment

Check the [package, shared-host and MongoDB requirements](../getting-started/installation.md#requirements), and review the [worker trust boundary](#security-and-monitoring) before passing a connection to workers.

## Startup and shutdown

Run the [FastAPI and Granian application](../examples/fastapi-shared.md) for a complete multi-process integration. Its parent starts the server once and passes `cache_server.connection` through a picklable application loader. Each worker's lifespan creates its client and attaches its manager.

The same ownership pattern works for background workers:

```python
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

from pymongo import MongoClient

from client_query_cache import SharedCacheManager, SharedCacheServer


def worker(connection):
    with (
        MongoClient("mongodb://localhost:27017", timeoutMS=5000) as client,
        SharedCacheManager(client, connection) as manager,
    ):
        return manager["catalogue"]["products"].find_one({"_id": "book"})


if __name__ == "__main__":
    with SharedCacheServer(
        "mongodb://localhost:27017",
        ("catalogue",),
        client_options={"timeoutMS": 5000},
    ) as cache_server:
        with ProcessPoolExecutor(
            max_workers=4, mp_context=get_context("spawn")
        ) as pool:
            print(list(pool.map(worker, (cache_server.connection,) * 4)))
```

This small program demonstrates ownership, not a guaranteed hit: the document must exist and initial reads can bypass while the stream starts. The web example verifies actual cross-process reuse.

An asyncio worker uses `async with AsyncMongoClient(...) as client, SharedCacheManager(client, connection) as manager` with the manager from `client_query_cache.asynchronous`. Alternatively, call `await SharedCacheManager.attach(client, connection)` and later `await manager.close()`. Construct and use that manager in one event loop.

Close managers before clients, stop workers, then close the server. Pass only `cache_server.connection` to workers. Clients, managers and server handles must not be reused after fork. Never start a server in each FastAPI lifespan: that produces independent caches. If the application supervisor cannot own and distribute one connection, use process-local managers.

## Which reads share data?

The [shared-read contract](../reference/shared-cache.md#worker-managers-and-reads) defines eligible queries, supported options, direct-read fallback and admission behavior. Use it to check whether your application's read mix can benefit from sharing.

## Collection names and capacity

Keep a fixed collection-name set for the server's lifetime. Ordinary collections such as `catalogue.products`, `catalogue.categories` and `catalogue.prices` are suitable even if their documents change continually. Those are three database/collection pairs, so `namespaces` must allow at least three, plus any other collections the workers access through the shared manager.

Creating `events_2026_10_17`, `events_2026_10_18`, or a fresh `request_<uuid>` collection indefinitely is different: every name introduces bookkeeping that can remain for the owner's lifetime, even after the collection is dropped. Increasing `namespaces` only increases the shared index's collection capacity; it does not bound all metadata or make this workload supported. Reusing the same collection names is suitable; continuously introducing new names is not.

For example, store events from every day in one `events` collection, with the day recorded in each document:

```json
[
  { "_id": "first-event", "day": "2026-10-17" },
  { "_id": "second-event", "day": "2026-10-18" }
]
```

Then `collection.find({"day": "2026-10-17"})` selects a day's events without creating a new collection. This is a direct PyMongo query; see the [shared-read contract](../reference/shared-cache.md#worker-managers-and-reads) for caching eligibility. MongoDB's [indexing guidance](https://www.mongodb.com/docs/manual/indexes/) explains when an index on the queried field helps.

If dynamic collection names are essential, use direct reads for those collections or a separate process-local manager with memory monitoring. Bounded shared metadata under name churn is tracked in [issue #282](https://github.com/alessio-locatelli/client-query-cache/issues/282).

Use the [SharedCacheConfig field reference](../reference/shared-cache.md#configuration) for memory and index sizing, and the [memory accounting reference](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/shared-cache.md#memory-outside-the-accounted-budget) when interpreting process measurements.

Connection capacity must cover each worker's control and request connections; synchronous request threads can need additional connections. Size the owner's MongoDB pool for one concurrent stream poll per active database, and worker pools for their own traffic. Precise native layout bounds and memory accounting are in the [maintainer reference](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/shared-cache.md).

## Consistency and recovery

For read-after-write and authorization decisions, follow the [consistency guidance](../usage/consistency.md).

If the owner silently stalls, hits stop within three seconds of its last successful upstream stream poll. That is an outage safeguard, not a maximum write-to-invalidation delay. Detected transport disconnects disable the affected mapping immediately. During temporary owner outages, workers use their own clients for direct reads, with bounded attachment attempts and retry cooldowns. The database operation still depends on the client's timeouts and can fail.

Use [`cache_server.restart()`](../reference/shared-cache.md#server-and-connection) for explicit cache-owner recovery. There is no automatic election or cross-host failover. Parent loss stops the owner. See the [API failure reference](../reference/shared-cache.md#diagnostics-and-failures) for errors that require application or operator action.

## Security and monitoring

Keep `SharedCacheConnection` private; do not log or persist it. All participants must use the same MongoDB deployment, credentials and read visibility. A connection grants access to every configured database. Never share it across security principals or mutually untrusted workers, even if collection names contain tenant IDs.

The private Unix endpoint is restricted to its operating-system user and requires the connection credential. Workers receive read-only shared value mappings, but every credential holder is trusted to read all shared values and submit values for caching. Sharing is not an authorization boundary. Follow the [freshness and authorization guidance](../usage/consistency.md#freshness-and-authorization) when access changes.

Use the [shared-manager monitoring guide](monitoring.md#shared-manager-diagnostics) to interpret worker counters and investigate low reuse. The [release workload measurements](../benchmarks/shared-cache.md) provide a comparison to reproduce for your application.
