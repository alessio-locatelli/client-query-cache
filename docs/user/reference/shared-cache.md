# Shared cache API

Choose this API for [eligible `_id` reads](#worker-managers-and-reads) across [trusted same-host workers](../operations/shared-cache.md#security-and-monitoring). See [manager selection](../getting-started/choose-a-manager.md) for the comparison and [shared deployment](../operations/shared-cache.md) for lifecycle, security and recovery. The [FastAPI example](../examples/fastapi-shared.md) is executable.

## Server and connection

```python
from client_query_cache import SharedCacheConfig, SharedCacheServer

with SharedCacheServer(
    mongodb_uri,
    ("catalogue",),
    config=SharedCacheConfig(budget_bytes=128 * 1024 * 1024),
    client_options={"timeoutMS": 5000},
) as cache_server:
    connection = cache_server.connection
    # Pass connection to workers and wait for them to finish within this block.
```

`SharedCacheServer(mongodb_uri, databases, *, config=SharedCacheConfig(), client_options=None)` starts an owner process immediately. `databases` is a nonempty tuple of distinct, nonempty database names. `client_options` configures the owner's own PyMongo client; see the [owner and worker access requirements](../operations/shared-cache.md#security-and-monitoring). Owner change streams use a fixed 100 ms maximum idle wait; the shared API exposes no await-time override.

`cache_server.connection` is a picklable `SharedCacheConnection`, carrying private attachment credentials. Follow the [connection security requirements](../operations/shared-cache.md#security-and-monitoring) when distributing it.

`cache_server.restart()` replaces the shared cache owner process with an empty cache at the same endpoint. Attached workers reconnect lazily and warm again. `cache_server.close()` stops and reaps it; close is repeat-safe. Both must run in the creating parent. The parent must stop workers before closing the server. The server supports synchronous `with`, including for an asyncio application whose workers use async managers.

## Worker managers and reads

```python
from client_query_cache import SharedCacheManager

with SharedCacheManager(client, connection) as manager:
    products = manager.get_cached_collection(client["catalogue"]["products"])
    product = products.find_one({"_id": "book"})
```

For asyncio, import `SharedCacheManager` from `client_query_cache.asynchronous` and enter it with `async with`, or use `manager = await SharedCacheManager.attach(client, connection)`. Construct and use it in one running event loop. Call `await manager.close()` before closing its client. Cancellation is propagated after cleanup finishes.

Both variants provide `client`, `get_cached_collection(collection)`, `manager[database][collection]` and `close()`. They return `SharedCachedCollection` views with `.raw` for direct PyMongo operations. The supplied collection must belong to the worker's client; foreign-client collections raise `ValueError`. Creating several views is safe; retain one for repeated use. Closing a manager closes its attachments, leaving the client, other workers and server alive. Repeated closes are safe.

Only deterministic `find_one(filter, projection=None, *, collation=None, **kwargs)` reads with an exact `_id` and no other filter predicates can cache. Projections and explicit simple collation are supported, but the collection's default collation must itself be simple (binary). Custom document classes and custom codec registries bypass. Missing documents can be cached. The normal [session, read-profile, query-safety and collection-type bypass rules](api.md#bypass-conditions) also apply.

`find`, `aggregate`, `count_documents`, `estimated_document_count`, `distinct` and broader `find_one` calls execute through PyMongo, without a second process-local cache. `find()` returns a native cursor immediately; await `aggregate()` with asyncio. Use the raw collection for writes and administration. Eligible misses use primary, majority reads and may return before shared admission completes; receiving a value is not proof of admission.

Support for caching these other reads across workers is tracked in [issue #295](https://github.com/alessio-locatelli/client-query-cache/issues/295).

## Configuration

`SharedCacheConfig` configures the server, not individual workers. Every field requires a positive built-in integer; booleans and numeric coercions are rejected with `CacheConfigurationError`.

| Field             | Default | Application meaning                                                                                |
| ----------------- | ------- | -------------------------------------------------------------------------------------------------- |
| `budget_bytes`    | 64 MiB  | Accounted cached BSON across all configured databases and workers                                  |
| `max_entry_bytes` | 1 MiB   | Largest encoded cached value; must not exceed the budget or arena                                  |
| `arena_bytes`     | 80 MiB  | Shared storage for encoded values, separate from the accounted budget                              |
| `slots`           | 65,536  | Shared index capacity; must be a supported power of two                                            |
| `namespaces`      | 1,024   | Maximum tracked database/collection pairs; drops free capacity and additional names bypass caching |
| `connections`     | 256     | Attachment and request connections across workers; at least two                                    |

The arena stores encoded documents. Increasing it adds storage headroom without increasing the accounted cache budget. An entry can fit the budget but fail publication because the index or arena is full. Reads still deliver their result; repeated reads may miss. See [collection-name examples and connection sizing guidance](../operations/shared-cache.md#collection-names-and-capacity) before increasing limits.

These settings do not cap RSS or total container memory. Native layout upper bounds are checked before allocation; their exact values and additional memory costs are in the [maintainer reference](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/shared-cache.md#native-capacity-limits).

## Diagnostics and failures

`manager.snapshot()` returns an immutable `SharedCacheStatistics`, synchronously in both APIs. See [shared-manager diagnostics](../operations/monitoring.md#shared-manager-diagnostics) for its fields, scope and telemetry limitations.

Invalid credentials, malformed protocol replies and persistent endpoint permission failures remain errors. Invalid server configuration or failed owner startup raises `CacheConfigurationError`; use after close, inherited manager/server use or an incorrect asyncio loop raises `CacheClosedError`. PyMongo reads retain driver errors and timeouts. See [recovery and its progress-expiry safeguard](../operations/shared-cache.md#consistency-and-recovery).
