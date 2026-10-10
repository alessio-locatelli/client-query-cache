# Coherent client-side caching for PyMongo

[![PyPI](https://img.shields.io/pypi/v/client-query-cache?color=lightgrey)](https://pypi.org/project/client-query-cache/)
[![Python](https://img.shields.io/pypi/pyversions/client-query-cache)](https://alessio-locatelli.github.io/client-query-cache/getting-started/installation/)
[![Coverage](https://img.shields.io/badge/coverage-100%25-brightgreen)](https://github.com/alessio-locatelli/client-query-cache/actions/workflows/test.yml)
[![Typing](https://img.shields.io/pypi/types/client-query-cache)](https://pypi.org/project/client-query-cache/)

`client-query-cache` uses MongoDB change streams to keep cached reads coherent. It supports synchronous and asyncio applications without requiring a separate cache server.

Cache hits are served from process memory, reducing read latency and database load in read-heavy applications. The library is tested against real MongoDB replica sets, including concurrency stress tests, and automated checks guard its performance and memory use against regressions.

![Illustrative read latency on a logarithmic scale: direct local MongoDB read, 120 microseconds; direct Atlas M0 read, 79.4 milliseconds; cached read in either deployment, about 61 microseconds.](docs/user/assets/benchmark-latency-light.svg)

Results vary by workload and deployment. [Measurements and methodology](https://alessio-locatelli.github.io/client-query-cache/benchmarks/).

Caching requires [MongoDB 8.0+ on a replica set or sharded cluster](https://alessio-locatelli.github.io/client-query-cache/getting-started/installation/#requirements). Reads on standalone servers and older MongoDB versions run through PyMongo without caching.

Invalidation is asynchronous: a cached read can return a preceding value until the write's change-stream event is processed. Use PyMongo directly when a read must immediately observe a preceding write; see [consistency](https://alessio-locatelli.github.io/client-query-cache/usage/consistency/).

Eligible cache misses read from the primary with `majority` read concern, even when the collection leaves read concern unspecified, so only majority-committed results enter the cache. Uncached PyMongo reads use the deployment's default read concern, normally `local`. The two usually perform alike, but while replication lags or data-bearing members are unavailable, a miss can return older data or fail where an uncached read would not. Majority admission does not make cache hits current: invalidation remains asynchronous. See [bypass conditions](https://alessio-locatelli.github.io/client-query-cache/reference/api/#bypass-conditions).

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
    CacheManager(client) as cache_manager,
):
    collection = client["client_query_cache_tutorial"]["items"]
    cached_collection = cache_manager.get_cached_collection(collection)
    collection.replace_one(
        {"_id": "example"}, {"_id": "example", "value": 42}, upsert=True
    )
    cached_collection.find_one({"_id": "example"})  # Reads from MongoDB.
    cached_collection.find_one({"_id": "example"})  # Repeated reads can use the cache.
```

## References

[Getting started](https://alessio-locatelli.github.io/client-query-cache/getting-started/synchronous/) · [Benchmarks](https://alessio-locatelli.github.io/client-query-cache/benchmarks/) · [Examples](https://alessio-locatelli.github.io/client-query-cache/examples/)

---

> MongoDB is a registered trademark of MongoDB, Inc. This project is independent and is not affiliated with or endorsed by MongoDB, Inc.
