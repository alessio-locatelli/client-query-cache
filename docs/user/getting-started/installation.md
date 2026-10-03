# Installation

`client-query-cache` adds a read cache to applications using PyMongo directly. It supports synchronous and asyncio clients and needs no separate cache server.

## Requirements

- Python 3.14.6 or newer and PyMongo 4.18.1 or newer, as declared by the package.
- Effective caching requires MongoDB 8.0 or newer on a replica set or sharded cluster. Change streams are unavailable on standalone servers; the library also enforces its MongoDB version floor at startup.
- A caller-owned PyMongo client with access to the collections and their database change stream.

Reads and writes work against deployments PyMongo supports. When the deployment cannot support caching, the manager logs a warning and reads bypass the cache for that database. The underlying PyMongo call retains its own errors and availability requirements.

## Install

```bash
uv add client-query-cache
```

Or install with pip:

```bash
pip install client-query-cache
```

For optional telemetry, install `client-query-cache[otel]` and follow [Monitoring](../operations/monitoring.md#opentelemetry-metrics).

## First cached read

Follow the complete [synchronous tutorial](synchronous.md) or [asyncio tutorial](asyncio.md). Both use a MongoDB deployment on `localhost:27017`; use your application's connection string when constructing the client.

Writes use the PyMongo collection. Invalidation is asynchronous, so a cached read can return a preceding value until its change-stream event is processed. See [consistency](../usage/consistency.md) before choosing which reads to cache.
