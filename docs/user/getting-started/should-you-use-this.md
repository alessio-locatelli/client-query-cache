# Should you use this?

Consider this library when an application repeatedly reads the same MongoDB data, can tolerate asynchronous invalidation, and keeps worker processes alive long enough to reuse their caches. A hit avoids a database query. The [benchmark results](../benchmarks/index.md) measure specific read operations; they do not predict the speedup of a whole HTTP request.

## Check the fit

| Question                                                             | What to check                                                                                                                                                                                                                                     |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Can this read return a preceding value after a write?                | Use cached reads only where that delay is acceptable. For write responses, payments, inventory commitments, and current authorization, use appropriate [direct reads and consistency controls](../usage/consistency.md).                          |
| Will the same queries repeat before relevant writes invalidate them? | Exact-identity reads can survive unrelated document writes; broader collection queries lose reuse more often. Check [query eligibility](../usage/cached-reads.md) and measure hits under your actual write traffic.                               |
| Does the deployment support caching?                                 | Check the [Python, PyMongo, MongoDB topology, and permission requirements](installation.md#requirements). A working database connection alone does not establish cache eligibility.                                                               |
| Do workers need to share the same hot documents?                     | Choose [shared or process-local caching](choose-a-manager.md). Sharing avoids duplicate documents and streams but adds an owner process; measure total memory and miss costs.                                                                     |
| Does the cache improve the application?                              | Compare application latency, database traffic, CPU, memory, hit rate, and bypasses with caching enabled and disabled. The [catalogue rollout example](../examples/fastapi.md#feature-flagged-rollout) demonstrates this application-owned switch. |

Try the [shared FastAPI application](../examples/fastapi-shared.md) for cross-worker reuse, or the [compact application](../examples/fastapi-minimal.md) and [eligibility exercise](../usage/eligibility.md) for broad process-local caching.

## Choose the caching layer

| Approach                     | When to consider it                                                                                       | What you still own                                                                                                                       |
| ---------------------------- | --------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| Indexed MongoDB queries      | Fresh database execution matters, queries rarely repeat, or indexes can remove the expensive work.        | Query/index design and the read/write consistency policy. Caching does not replace suitable indexes for misses.                          |
| This library                 | Repeated eligible reads benefit from avoiding a round trip, and asynchronous invalidation fits the data.  | Manager selection, memory, stream permissions, monitoring and parent/worker ownership when sharing.                                      |
| A shared cache such as Redis | Workers on different hosts need a common cache, or the application caches more than MongoDB read results. | A separate service, network calls, serialization, invalidation, and consistency policy. It is not a drop-in substitute for this library. |
| HTTP caching                 | Whole responses can be reused under an explicit HTTP cache policy.                                        | Response cache keys, freshness, validators, and authorization boundaries.                                                                |
| CDN or edge caching          | Cacheable responses or assets can be served near users before requests reach the application.             | Cache-control policy, private-content protection, and purge or expiry behavior.                                                          |

These approaches can be combined. Compare them at the layer where your application spends time; there is no measured universal ranking between them.
