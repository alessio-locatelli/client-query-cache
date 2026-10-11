# Compact FastAPI application

This application owns one `AsyncMongoClient` and one `CacheManager` per lifespan. GET reads use a cached collection; PATCH writes and reads its response directly in a causally consistent session with majority concerns. `/metrics/cache` returns the public cache snapshot. The manager closes before its client.

Run the self-check from the repository checkout:

```console
uv run examples/fastapi_minimal_example.py
```

Use a disposable MongoDB 8.0+ replica set. The self-check resets and cleans `client_query_cache_example_fastapi_minimal`; the application lifespan itself never resets data. See [example prerequisites](index.md#prerequisites) for connection settings. The self-check uses FastAPI's in-process client and exposes no HTTP listener. Supply your own authentication before serving these endpoints; the [advanced catalogue](fastapi.md) demonstrates trusted identity and tenant separation.

## Application

The application and verification share one [canonical source](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/fastapi_minimal_example.py). Imports are shown separately from the application below.

<!-- fmt:off -->

```python
--8<-- "examples/fastapi_minimal_example.py:imports"
```

```python
--8<-- "examples/fastapi_minimal_example.py:application"
```

<!-- fmt:on -->

The 1 KiB entry limit makes an oversized read easy to observe in the [eligibility exercise](../usage/eligibility.md). Choose your application's budget using [capacity guidance](../operations/deployment.md#capacity-estimation).

## Read and write observations

The self-check verifies a miss followed by a hit, then updates the document through PATCH. The PATCH response contains the updated description without using the cache. It prints subsequent GET observations until an updated cache hit is observed, and checks the stream's invalidation count increased.

One possible ordering is:

```text
GET: original description, cache hit
PATCH: write acknowledged, direct response contains updated description
GET: original description, cache hit while the event is in flight
stream processes the event and invalidates the stored result
GET: updated description, cache miss
GET: updated description, cache hit
```

The event can arrive before the first GET after PATCH, so that GET can already return the new value. The program accepts both orderings; it does not force a stale read or print an invented event arrival time. Its five-second polling deadline is a self-check limit, not a freshness guarantee. Direct reads do not refresh cached content; see [consistency](../usage/consistency.md).

For deployment flags, pagination, and authorization, use the [catalogue reference](fastapi.md). For exporting counters to your telemetry system, use [monitoring](../operations/monitoring.md).
