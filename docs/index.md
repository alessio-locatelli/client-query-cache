# client-query-cache

Add an in-process read cache to a PyMongo application, kept coherent using MongoDB
change streams. The library supports synchronous and asyncio clients without a
separate cache server.

These guides describe the current `main` branch. Options may differ from your
installed release.

## Install and start

The library requires Python 3.14.6 or newer. Effective caching requires MongoDB 8.0
or newer on a replica set or sharded cluster; see the
[system requirements](architecture.md#system-requirements).

```bash
uv add client-query-cache
```

Or use `pip install client-query-cache`. Follow the
[README quick start](https://github.com/alessio-locatelli/client-query-cache/blob/main/README.md#usage)
for synchronous and asyncio programs.

## Find guidance

- [API reference](api-reference.md): configure the manager, cached reads, and raw fallback.
- [Architecture and operations](architecture.md): plan capacity, monitor stream health,
  and understand recovery and consistency.
- [Performance](stream-cost-benchmarks.md): evaluate caching for your workload and
  reproduce the retained measurements.
- [Examples](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/README.md):
  run integrations with MongoDB-backed libraries.

Writes go through your PyMongo collection. Invalidation is asynchronous, so use
PyMongo directly for a read that must immediately observe a preceding write.
