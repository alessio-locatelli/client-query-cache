# Share a cache across application workers

Use `SharedCacheServer` when [trusted workers](#security-and-monitoring) on one host repeatedly make [eligible collection reads](../reference/shared-cache.md#worker-managers-and-reads). The server starts one cache-owner process; workers reuse its values and one change stream per active database. Sync and asyncio workers can share the same server. Each worker still owns a PyMongo client for misses, writes and uncached reads.

Compare [the two managers](../getting-started/choose-a-manager.md) before adopting this model. Shared views cache the same six read methods as `CacheManager`, with additional eligibility restrictions. Sharing also requires an application parent that stays alive until every worker has stopped.

## Supported deployment

Check the [package, shared-host and MongoDB requirements](../getting-started/installation.md#requirements), and review the [worker trust boundary](#security-and-monitoring) before passing a connection to workers.

## Startup and shutdown

### Who starts and stops the processes?

The application parent creates one `SharedCacheServer`, then starts the workers and gives them the cache server's connection. A process supervisor is the program that starts the application and can restart it after a crash. In this setup, it manages the parent and workers as a group.

Run the [FastAPI and Granian example](../examples/fastapi-shared.md) to see this setup. Each worker opens its own PyMongo client and attaches to the shared cache.

The same ownership pattern works for background workers:

```python
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

from client_query_cache import SharedCacheServer


def worker(connection):
    from pymongo import MongoClient

    from client_query_cache import SharedCacheManager

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

Close managers before clients, stop workers, then close the server. Pass only `cache_server.connection` to workers. Clients, managers and server handles must not be reused after fork. Never start a server in each FastAPI lifespan: that produces independent caches. If the application parent cannot pass the same connection to every worker, use process-local managers.

Server close and restart wait for the owner process to exit. PyMongo's background thread shutdown can add roughly half a second to that wait. [MongoDB issue PYTHON-4877](https://jira.mongodb.org/browse/PYTHON-4877) · [Shutdown follow-up](https://github.com/alessio-locatelli/client-query-cache/issues/547)

To disable shared caching, follow [Rollback to plain PyMongo](../reference/api.md#rollback-to-plain-pymongo).

## Which reads share data?

The [shared-read contract](../reference/shared-cache.md#worker-managers-and-reads) defines eligible queries, supported options, direct-read fallback and admission behavior. Use it to check whether your application's read mix can benefit from sharing.

## Collection names and capacity

`namespaces` sets how many database/collection pairs the server can track at once. Size it for the collections workers use concurrently. A processed collection drop releases its capacity, so applications can create, use and remove collections over time.

When every slot is in use, reads for another collection still run through MongoDB and bypass shared caching. They do not add namespace metadata; caching can resume after a tracked collection is dropped. For example, `events_2026_10_17` and `events_2026_10_18` can be separate collections when the configured capacity covers the number used at the same time.

For example, store events from every day in one `events` collection, with the day recorded in each document:

```json
[
  { "_id": "first-event", "day": "2026-10-17" },
  { "_id": "second-event", "day": "2026-10-18" }
]
```

Then `collection.find({"day": "2026-10-17"})` selects a day's events without creating a new collection. See the [shared-read contract](../reference/shared-cache.md#worker-managers-and-reads) for caching eligibility. MongoDB's [indexing guidance](https://www.mongodb.com/docs/manual/indexes/) explains when an index on the queried field helps.

Use the [SharedCacheConfig field reference](../reference/shared-cache.md#configuration) for memory and index sizing, and the [memory accounting reference](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/shared-cache.md#memory-outside-the-accounted-budget) when interpreting process measurements.

Connection capacity must cover each worker's control and request connections; synchronous request threads can need additional connections. If a needed connection cannot be opened, the read falls back to MongoDB with bounded retry cooldowns. Size the owner's MongoDB pool for one concurrent stream poll per active database, and worker pools for their own traffic. Precise native layout bounds and memory accounting are in the [maintainer reference](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/shared-cache.md).

## Consistency and recovery

For read-after-write and authorization decisions, follow the [consistency guidance](../usage/consistency.md).

If the owner silently stalls, hits stop within three seconds of its last successful upstream stream poll. That is an outage safeguard, not a maximum write-to-invalidation delay. Detected transport disconnects disable the affected mapping immediately. During temporary owner outages, workers use their own clients for direct reads, with bounded attachment attempts and retry cooldowns. The database operation still depends on the client's timeouts and can fail.

### Recover a worker group

On a supported Linux host, use a [process supervisor](#who-starts-and-stops-the-processes) to manage the application parent and its workers together. Shared caching has no automatic failover. Workers cannot take over as owner or switch to a cache on another host.

During recovery, keep sending traffic to the affected group if direct MongoDB reads can meet your latency and throughput requirements. Otherwise, stop routing production traffic to the group and verify cache hits with representative reads before restoring traffic. [Enable telemetry on the server](monitoring.md) to inspect [worker hit counts and owner snapshots](monitoring.md#shared-manager-diagnostics). Healthy change streams show that cache hits are possible. Use worker hit counts to confirm that they occur.

- **Owner exits while the parent is running.** Have the parent call [`cache_server.restart()`](../reference/shared-cache.md#server-and-connection) whether the workers are serving production traffic or waiting for recovery. The replacement starts with an empty cache at the same endpoint. Existing workers reconnect on later reads and fill it again. If the replacement owner fails to start, the restart closes the server. Check the [API failure reference](../reference/shared-cache.md#diagnostics-and-failures), resolve the cause, and replace the group as for parent loss.
- **Parent exits.** The owner stops. Have the supervisor stop any surviving workers from that group and launch a new application parent. The new parent starts its own server and distributes its new [private connection](#security-and-monitoring) to its replacement workers.
- **Roll out a replacement.** Start a new parent and worker group with their own cache. Check that the new group can handle traffic before routing requests to it. Stop sending new requests to the old group, let it finish the requests it already has, and follow the [shutdown order](#startup-and-shutdown). While both groups are running, budget for extra MongoDB reads as the new cache fills and for one change stream per active database in each owner. For example, 20 worker groups reading from the same database can open 20 streams for it, plus one for each overlapping replacement group that reads from it.

Each group is independent. For workloads that require shared cache state across hosts, compare [caching approaches](../getting-started/should-you-use-this.md#choose-the-caching-layer).

## Security and monitoring

Keep `SharedCacheConnection` private; do not log or persist it. All participants must use the same MongoDB deployment, credentials and read visibility. A connection grants access to every configured database. Never share it across security principals or mutually untrusted workers, even if collection names contain tenant IDs.

The private Unix endpoint is restricted to its operating-system user and requires the connection credential. Workers receive read-only shared value mappings, but every credential holder is trusted to read all shared values and submit values for caching. Sharing is not an authorization boundary. Follow the [freshness and authorization guidance](../usage/consistency.md#freshness-and-authorization) when access changes.

Use the [shared-manager monitoring guide](monitoring.md#shared-manager-diagnostics) to interpret worker statistics and the owner snapshot and to investigate low reuse. The [release workload measurements](../benchmarks/shared-cache.md) provide a comparison to reproduce for your application.
