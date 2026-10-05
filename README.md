# client-query-cache

[![Python 3.14.6+](https://img.shields.io/badge/python-3.14.6%2B-blue.svg)](https://www.python.org/downloads/)

Client-side caching for PyMongo applications, kept coherent using MongoDB change streams. It supports synchronous and asyncio clients, caches six read methods, and keeps writes on your PyMongo collection. No separate cache server is required.

**Built for production:** Designed for high-traffic, read-heavy applications, with cache hits served from memory to reduce latency and database load. Quality is backed by a 100% test-coverage requirement, real MongoDB integration and concurrency stress tests, and automated performance and memory regression checks.

Caching requires [MongoDB 8.0+ on a replica set or sharded cluster](https://alessio-locatelli.github.io/client-query-cache/getting-started/installation/#requirements). Reads on standalone servers and older MongoDB versions run through PyMongo without caching.

Invalidation is asynchronous: a cached read can return a preceding value until the write's change-stream event is processed. Use PyMongo directly when a read must immediately observe a preceding write.

## Install

```bash
uv add client-query-cache
```

Or use `pip install client-query-cache`.

## Documentation

The [documentation site](https://alessio-locatelli.github.io/client-query-cache/) opens the latest release guides. Select **Development (main)** for unreleased changes.

- [Getting started](https://alessio-locatelli.github.io/client-query-cache/getting-started/installation/): installation and complete synchronous and asyncio tutorials.
- [Usage](https://alessio-locatelli.github.io/client-query-cache/usage/cached-reads/): cached reads and consistency.
- [Benchmarks](https://alessio-locatelli.github.io/client-query-cache/benchmarks/): workload evaluation and retained measurements.
- [Examples](https://alessio-locatelli.github.io/client-query-cache/examples/): runnable requests-cache, Celery, and py-abac integrations.
- [API reference](https://alessio-locatelli.github.io/client-query-cache/reference/api/): configuration, limits, errors, and raw fallback.
- [Operations](https://alessio-locatelli.github.io/client-query-cache/operations/): deployment, capacity, security, recovery, and monitoring.

The repository's [example sources and command catalogue](examples/README.md) and [contributor instructions](CONTRIBUTING.md) are available for checkout-based work.

---

> MongoDB is a registered trademark of MongoDB, Inc. This project is independent and is not affiliated with or endorsed by MongoDB, Inc.
