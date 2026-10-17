# client-query-cache

Cache repeated PyMongo queries in your application, with synchronous and asyncio APIs. MongoDB change streams invalidate affected results when data changes, including writes by other clients.

For multiple trusted workers on one host, a **Rust-backed native shared cache** lets processes reuse the same cached documents and one change stream per active database. Workers avoid storing their own copies of the hot data. A process-local manager also supports caching broader queries, cursors, aggregations and counts.

Sharing has an owner process and admission costs. The [measured comparisons](benchmarks/shared-cache.md) show hot-read benefits and cold-read costs; neither Rust nor sharing guarantees a win for every workload.

## Install and start

1. [Check whether caching fits](getting-started/should-you-use-this.md) your consistency and workload needs.
2. [Choose a manager](getting-started/choose-a-manager.md): broad reads within a process, or shared `_id` reads across workers.
3. [Check the requirements and install](getting-started/installation.md).
4. Follow the [synchronous](getting-started/synchronous.md) or [asyncio](getting-started/asyncio.md) quick start, or run the [shared FastAPI application](examples/fastapi-shared.md).

Before using cached reads, review the [consistency guarantees](usage/consistency.md) and plan direct PyMongo reads where freshness is required.

## Operate the application

- [Cached reads](usage/cached-reads.md) and [eligibility](usage/eligibility.md) explain which requests can hit.
- [Deployment](operations/index.md) covers ownership, memory, security and recovery for both managers.
- [Monitoring](operations/monitoring.md) explains the diagnostics available in each mode.
- [API reference](reference/api.md) gives exact call and configuration contracts.
- [Examples](examples/index.md) provide runnable web applications and adapters.
