# A cache shared by application workers

`SharedCacheServer` shares cached `_id` documents and one change stream per active database across trusted workers on one Linux host. Sync and asyncio workers can attach to the same server. Each worker still needs its own PyMongo client for misses and writes.

## Supported deployment

Use CPython 3.14 or newer on Linux x86-64, glibc 2.28 or newer, and a Linux 5.1 or newer kernel with `memfd` sealing and `/proc` available. The release wheel contains the native module; applications do not need Rust. Source installations require [Rust and Cargo](https://rust-lang.org/tools/install). Free-threaded Python, other architectures, other operating systems and cross-host sharing are outside this initial contract.

Use a stable set of collection names within the configured databases, and size `namespaces` for that set. The slot limit bounds the shared index, not all Python metadata. Sustained collection-name churn is outside this initial contract; [issue #282](https://github.com/alessio-locatelli/client-query-cache/issues/282) tracks bounded metadata for that workload.

Use a replica set or sharded cluster running MongoDB 8.0 or newer, with database change-stream and collection metadata permissions. Give the owner and workers the same deployment, credentials and read visibility. One connection grants access to every configured database: never share it across tenants, users with different permissions, or mutually untrusted workers.

Start one server in your application's parent, then pass `server.connection` to workers. The connection is picklable for spawned processes; it contains an attachment credential, so keep it private. Construct PyMongo clients and managers inside each worker. Reuse the manager throughout that worker's lifetime. Do not put a server in every worker's FastAPI lifespan: that creates independent caches. Application supervisors without a parent startup hook should use the process-local `CacheManager`.

```python
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

from pymongo import MongoClient

from client_query_cache import SharedCacheManager, SharedCacheServer


def worker(connection):
    with (
        MongoClient(
            "mongodb://localhost:27017", serverSelectionTimeoutMS=5000
        ) as client,
        SharedCacheManager(client, connection) as manager,
    ):
        items = manager.get_cached_collection(client.catalogue.items)
        return items.find_one({"_id": "example"})


if __name__ == "__main__":
    with SharedCacheServer(
        "mongodb://localhost:27017",
        ("catalogue",),
        client_options={"serverSelectionTimeoutMS": 5000},
    ) as server:
        with ProcessPoolExecutor(
            max_workers=4, mp_context=get_context("spawn")
        ) as pool:
            print(list(pool.map(worker, (server.connection,) * 4)))
```

An asyncio worker uses the same connection:

```python
from pymongo import AsyncMongoClient

from client_query_cache.asynchronous import SharedCacheManager


async def worker(connection):
    async with (
        AsyncMongoClient("mongodb://localhost:27017") as client,
        SharedCacheManager(client, connection) as manager,
    ):
        return await manager["catalogue"]["items"].find_one({"_id": "example"})
```

Alternatively, use `await SharedCacheManager.attach(client, connection)` and subsequently `await manager.close()`. Construct and use an asyncio manager in one event loop. Close worker managers before their clients, stop workers, then close the server. Closing a manager preserves the client and the server. Both server and manager close are safe to repeat; async cleanup finishes before propagating cancellation. Clients, managers and servers must not be used after inheritance through fork; pass the connection and create fresh worker resources.

## Reads and consistency

Only deterministic `find_one()` reads with an exact `_id` and no additional filter predicates are shared. Projections are supported. Collections must use simple default collation; explicit non-simple collations execute through PyMongo; custom document classes and custom codec registries bypass sharing. Sessions, unsupported read concerns/preferences and other normal cache bypass conditions still execute through PyMongo. `find()`, aggregation, counts, distinct and non-identity reads always execute through PyMongo; `find()` returns a native cursor immediately. Use the original collection or `.raw` for writes.

The first read may run uncached while metadata and the database stream start. Eligible misses use primary, majority reads and queue admission without waiting for the owner to select the result. Full queues or oversized entries can skip caching without changing the delivered document. `manager.snapshot()` reports this worker's hits, misses and bypasses; these counts do not aggregate other workers.

Invalidation is asynchronous. A hit can precede a concurrent write's change-stream event; use direct PyMongo reads for authorization or read-after-write requirements. If the owner silently stalls or loses upstream progress, hits stop within three seconds of the last successful stream poll. Detected disconnects disable their mapping immediately. During an outage, existing and newly started workers use their own PyMongo clients, with bounded attachment attempts and retry cooldown. Managers reconnect lazily when the owner returns. Credential and configuration rejections, protocol errors and persistent access failures remain errors; an unreachable owner cannot validate attachment credentials until it returns. The database read itself remains subject to the client's timeouts.

`server.restart()` replaces the owner with an empty cache at the same endpoint. Attached workers reconnect lazily, discard previous metadata and warm again. A restarted owner cannot revive earlier admissions. There is no automatic owner election or cross-host recovery. Parent loss stops the owner; normal application shutdown should always use the context managers above.

## Capacity and security

Pass `config=SharedCacheConfig(...)` to the server. All fields require positive built-in integers:

| Field             | Default | Meaning                                                                                  |
| ----------------- | ------- | ---------------------------------------------------------------------------------------- |
| `budget_bytes`    | 64 MiB  | Accounted cached entries across the owner.                                               |
| `max_entry_bytes` | 1 MiB   | Maximum encoded value, no larger than the budget or arena.                               |
| `slots`           | 65,536  | Index capacity; use a power of two. Collisions or arena pressure can refuse publication. |
| `arena_bytes`     | 80 MiB  | Shared payload arena capacity.                                                           |
| `namespaces`      | 1,024   | Collection slots in the shared index; size for the stable collection set.                |
| `connections`     | 256     | Transport connections, including each worker's control connection; minimum two.          |

Arena capacity cannot exceed 34,359,738,360 bytes; namespace count cannot exceed 4,294,967,295. Slot count must fit the native address-space limit. Workers retain up to 8,192 key encodings. The owner separately retains up to 1,024 decoded read-shape keys and 256 encoded read-shape keys. Each cache admits only keys whose encoded size is at most 4 KiB; canonical Python objects add memory overhead. Larger identifiers and read shapes remain usable without being retained in these key caches. These are separate capacities, not a total RSS limit. The index also consumes about 4 MiB at its default slot count. Each attached worker maps shared pages and owns a bounded admission queue; its client, decoded documents and temporary frames consume additional memory. A manager needs a control connection plus a request connection; synchronous request threads can use additional connections. Size the owner's pool for one concurrent stream poll per active database, and workers' pools for their own requests.

The private Unix endpoint is accessible only to its operating-system user and requires a random capability. Cached values are in sealed read-only mappings in workers. All capability holders are trusted equally: a worker can read all shared values and submit values for admission. This is an application cache, not an authorization boundary. Credential or role changes alone do not invalidate cached values; restart the owner or use direct reads when authorization changes.

See the [release workload measurements](../benchmarks/shared-cache.md) for measured benefits and miss costs. Choose the process-local manager when you need its broader cached-read scope.
