# Should you use this?

Consider this library when an application repeatedly reads the same MongoDB data, can tolerate asynchronous invalidation, and keeps worker processes alive long enough to reuse their caches. A hit avoids a database query. The [benchmark results](../benchmarks/index.md) measure specific read operations; they do not predict the speedup of a whole HTTP request.

## Check the fit

| Question                                                             | What to check                                                                                                                                                                                                                                     |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Can this read return a preceding value after a write?                | Use cached reads only where that delay is acceptable. For write responses, payments, inventory commitments, and current authorization, use appropriate [direct reads and consistency controls](../usage/consistency.md).                          |
| Will the same queries repeat before relevant writes invalidate them? | Exact-identity reads can survive unrelated document writes; broader collection queries lose reuse more often. Check [query eligibility](../usage/cached-reads.md) and measure hits under your actual write traffic.                               |
| Does the deployment support caching?                                 | Check the [Python, PyMongo, MongoDB topology, and permission requirements](installation.md#requirements). A working database connection alone does not establish cache eligibility.                                                               |
| Can each worker afford its own cache?                                | Workers warm independently and multiply memory budgets and streams. Use [capacity estimates](../operations/deployment.md#capacity-estimation), including memory beyond stored BSON.                                                               |
| Does the cache improve the application?                              | Compare application latency, database traffic, CPU, memory, hit rate, and bypasses with caching enabled and disabled. The [catalogue rollout example](../examples/fastapi.md#feature-flagged-rollout) demonstrates this application-owned switch. |

Try the [compact FastAPI application](../examples/fastapi-minimal.md) and [eligibility exercise](../usage/eligibility.md) to see the lifecycle and counters before adapting the larger catalogue.

## Choose the caching layer

| Approach                     | When to consider it                                                                                      | What you still own                                                                                                                       |
| ---------------------------- | -------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Indexed MongoDB queries      | Fresh database execution matters, queries rarely repeat, or indexes can remove the expensive work.       | Query/index design and the read/write consistency policy. Caching does not replace suitable indexes for misses.                          |
| This process-local cache     | Repeated eligible reads benefit from avoiding a round trip, and asynchronous invalidation fits the data. | Per-worker memory, independent warming, stream permissions, and monitoring.                                                              |
| A shared cache such as Redis | Workers need to reuse a shared cache or cache data beyond MongoDB read results.                          | A separate service, network calls, serialization, invalidation, and consistency policy. It is not a drop-in substitute for this library. |
| HTTP caching                 | Whole responses can be reused under an explicit HTTP cache policy.                                       | Response cache keys, freshness, validators, and authorization boundaries.                                                                |
| CDN or edge caching          | Cacheable responses or assets can be served near users before requests reach the application.            | Cache-control policy, private-content protection, and purge or expiry behavior.                                                          |

These approaches can be combined. Compare them at the layer where your application spends time; there is no measured universal ranking between them.
