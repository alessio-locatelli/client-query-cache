# Choose a cache manager

Use **`CacheManager`** when each process can manage its own cache. Use **`SharedCacheManager`** when several trusted workers on one host repeatedly make the same collection reads.

Both offer synchronous and asyncio versions. Import the synchronous manager from `client_query_cache`, or its asyncio counterpart from `client_query_cache.asynchronous`.

| Decision          | `CacheManager`                                                                                      | `SharedCacheManager`                                                                                                 |
| ----------------- | --------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| Cached operations | Eligible `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, `distinct` | [The same six methods, with shared eligibility restrictions](../reference/shared-cache.md#worker-managers-and-reads) |
| Other reads       | Ineligible requests execute through PyMongo                                                         | Ineligible requests execute through PyMongo                                                                          |
| Process scope     | One independent cache per manager                                                                   | Values and one stream per active database shared by attached sync/async workers                                      |
| Deployment        | Client and manager created in each process                                                          | One parent-owned `SharedCacheServer`; each worker creates its own client and manager                                 |
| Platform          | [Package requirements](installation.md#requirements)                                                | [Additional shared-host requirements](installation.md#requirements)                                                  |
| Performance       | No owner process; workers warm and store data independently                                         | Avoids duplicate document storage and streams; owner startup, memory and miss handling add costs                     |
| Lifecycle         | Close manager before its client                                                                     | Close worker managers before clients, stop workers, then close server                                                |
| Diagnostics       | [Detailed cache and stream diagnostics](../operations/monitoring.md#observability)                  | [Worker counters](../operations/monitoring.md#shared-manager-diagnostics)                                            |

For example, `find_one({"_id": order_id, "tenant_id": tenant_id})` can share a tenant-filtered order across workers, and `find({"status": "active"}).sort("_id").limit(20)` can share a page. Never remove an authorization predicate to obtain a cache hit.

Review [consistency guarantees](../usage/consistency.md) for freshness-sensitive operations and the [shared-cache trust boundary](../operations/shared-cache.md#security-and-monitoring) before distributing a connection to workers.

## Why two managers?

The choice changes deployment requirements and who owns the cache lifetime. A shared cache needs a parent that outlives its workers, shared memory, and a common security identity. A process-local cache needs none of that coordination and supports a broader range of codec and collation profiles. Keeping those choices explicit prevents a deployment setting from silently changing deployment requirements or creating an owner in every worker. The [maintainer decision](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/decisions/keep-explicit-cache-managers.md) evaluates a unified interface and records the tradeoffs.

Sharing does not automatically save total application memory or CPU: the owner has its own baseline, and misses perform admission work. Read the [public API measurements](../benchmarks/shared-cache.md) and test your read mix, worker count and write rate.

## Next step

- For process-local caching, follow the [synchronous](synchronous.md) or [asyncio](asyncio.md) tutorial, then the [compact FastAPI application](../examples/fastapi-minimal.md).
- For sharing, run the [FastAPI and Granian example](../examples/fastapi-shared.md), then follow the [shared deployment guide](../operations/shared-cache.md).
- If your workers cannot share a parent and host, use independent managers or an application-level external cache. There is no cross-host shared-cache service or automatic owner election.
