# FastAPI with shared caching and Granian

Run multiple actual HTTP workers that reuse product documents and one MongoDB change stream. One parent starts `SharedCacheServer`; Granian passes its connection to spawned application loaders. Each worker's FastAPI lifespan creates an `AsyncMongoClient` and attaches an asyncio `SharedCacheManager`. The owner stays outside the workers.

Use this example for same-host services dominated by `find_one({"_id": ...})` reads. For cached pages, aggregation or counts, use the process-local [compact application](fastapi-minimal.md) or [tenant-aware catalogue](fastapi.md). See [manager selection](../getting-started/choose-a-manager.md) for the full comparison.

## Run and verify

From the repository checkout, with the [example prerequisites](index.md#prerequisites):

```console
uv run examples/fastapi_shared_example.py
```

The self-check starts Granian with two spawned workers on a free localhost port and uses real HTTP connections. It resets and cleans `client_query_cache_example_fastapi_shared`; use a disposable deployment meeting the [MongoDB requirements](../getting-started/installation.md#requirements). It fails unless:

1. Two different worker PIDs answer HTTP requests.
2. Worker A warms a product and records a cache hit.
3. Worker B's first product read records a shared hit and **zero MongoDB `find` commands**.
4. A raw PATCH returns the updated document, invalidation forces a refetch, and both workers subsequently hit the updated value.
5. Both workers close their managers before their clients, and the parent closes the cache server after worker shutdown.

The response includes worker-local cumulative counters. The optional `worker_pid` query parameter rejects a request handled by another worker before accessing storage, so verification can target each process without warming the second worker accidentally. This is demonstration instrumentation, not a routing mechanism for an application. Snapshot differences only identify individual requests in this isolated, sequential self-check.

The program prints evidence resembling:

```text
shared hit: worker 123 warmed; worker 124 read with zero MongoDB finds
invalidation: both workers hit the updated document after a raw PATCH
worker 123: shared manager closed before client
worker 124: shared manager closed before client
parent: shared cache server closed after workers
```

Startup and admission can take several reads. The check allows preceding cached values after PATCH while waiting for updated hits; its deadlines bound the demonstration, not production freshness. There is no TTL or manual cache clear in the check. See [consistency](../usage/consistency.md).

## Serve the application

```console
uv run examples/fastapi_shared_example.py --serve --workers 4 --port 8000
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8000/products/book
```

Serve mode leaves existing data intact. Insert a product into `client_query_cache_example_fastapi_shared.products` using your normal MongoDB tools, for example `{_id: "book", description: "A product description"}`; a missing product returns 404. Update it with:

```console
curl -X PATCH http://127.0.0.1:8000/products/book \
  -H 'Content-Type: application/json' \
  -d '{"description":"An updated description"}'
```

PATCH uses PyMongo's `find_one_and_update(..., return_document=AFTER)` with majority write concern. Its response comes from the write, while subsequent GETs can lag until invalidation arrives. Stop with Ctrl+C for graceful cleanup.

This localhost demonstration has no authentication. Add trusted authentication and restrict diagnostics before exposing it. All shared workers must have the same database read visibility. Never remove tenant or permission predicates to make a query eligible for sharing.

## Application lifecycle

The example pins Granian 2.8.4 and uses its [programmatic `serve(target_loader=..., wrap_loader=False)` API](https://github.com/emmett-framework/granian/blob/v2.8.4/granian/server/common.py). A picklable `functools.partial` carries only the connection; it creates the FastAPI app inside each worker. The script selects the `spawn` process method and runs the ASGI lifespan in each worker. The ordinary `granian module:app --workers N` command alone cannot distribute this parent's live connection; run the provided launcher.

<!-- fmt:off -->

```python
--8<-- "examples/fastapi_shared_example.py:application"
```

<!-- fmt:on -->

The [complete source](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/fastapi_shared_example.py) includes imports, response types, command counting and the HTTP self-check. It is exercised by `just examples`. The parent and each worker use bounded MongoDB operation timeouts; configure those for your own service and shutdown policy. See [shared deployment](../operations/shared-cache.md) for capacity, outage behavior and security.
