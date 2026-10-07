# Coherent client-side caching for PyMongo

[![Python 3.14.6+](https://img.shields.io/badge/python-3.14.6%2B-blue.svg)](https://www.python.org/downloads/)

`client-query-cache` uses MongoDB change streams to keep cached reads coherent. It supports synchronous and asyncio applications without requiring a separate cache server.

**Built for production:** Designed for high-traffic, read-heavy applications, with cache hits served from memory to reduce latency and database load. Quality is backed by a 100% test-coverage requirement, real MongoDB integration and concurrency stress tests, and automated performance and memory regression checks.

![Illustrative read latency on a logarithmic scale: direct local MongoDB read, 120 microseconds; direct Atlas M0 read, 79.4 milliseconds; cached read in either deployment, about 61 microseconds.](docs/user/assets/benchmark-latency-light.svg)

Results vary by workload and deployment. [Measurements and methodology](https://alessio-locatelli.github.io/client-query-cache/benchmarks/).

Caching requires [MongoDB 8.0+ on a replica set or sharded cluster](https://alessio-locatelli.github.io/client-query-cache/getting-started/installation/#requirements). Reads on standalone servers and older MongoDB versions run through PyMongo without caching.

Invalidation is asynchronous: a cached read can return a preceding value until the write's change-stream event is processed. Use PyMongo directly when a read must immediately observe a preceding write.

## Quick start

```bash
uv add client-query-cache
```

Or use `pip install client-query-cache`.

```python
from pymongo import MongoClient

from client_query_cache import CacheManager

with (
    MongoClient("mongodb://localhost:27017") as client,
    CacheManager(client) as cache,
):
    users = cache.get_cached_collection(client["my_database"]["users"])
    users.find_one({"_id": "alice"})  # Reads from MongoDB.
    users.find_one({"_id": "alice"})  # Repeated reads can use the cache.
```

## References

[Getting started](https://alessio-locatelli.github.io/client-query-cache/getting-started/synchronous/) · [Benchmarks](https://alessio-locatelli.github.io/client-query-cache/benchmarks/) · [Examples](https://alessio-locatelli.github.io/client-query-cache/examples/)

---

> MongoDB is a registered trademark of MongoDB, Inc. This project is independent and is not affiliated with or endorsed by MongoDB, Inc.
