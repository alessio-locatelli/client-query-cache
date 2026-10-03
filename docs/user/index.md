# client-query-cache

Add an in-process read cache to an application using PyMongo directly. The library supports synchronous and asyncio clients and uses MongoDB change streams to invalidate cached results, without a separate cache server.

## Install and start

Start with [installation](getting-started/installation.md), then follow the complete [synchronous](getting-started/synchronous.md) or [asyncio](getting-started/asyncio.md) tutorial.

Caching requires MongoDB 8.0+ on a replica set or sharded cluster. Writes go through PyMongo. Invalidation is asynchronous, so use direct reads wherever freshness is required; see [consistency](usage/consistency.md).

## Find guidance

- [Usage](usage/cached-reads.md): choose cached reads and understand raw fallback.
- [Benchmarks](benchmarks/index.md): evaluate your workload and inspect reproducible measurement evidence.
- [Examples](examples/index.md): study and run integrations with MongoDB-backed libraries.
- [API reference](reference/api.md): exact options, limits, errors, and ownership contracts.
- [Operations](operations/index.md): plan capacity, security, recovery, and monitoring.
