# FastAPI catalogue

This example uses process-local `CacheManager`. For a single cache shared by real HTTP workers, run the [FastAPI and Granian example](fastapi-shared.md). See [manager selection](../getting-started/choose-a-manager.md) before deployment.

For a smaller starting point, use the [compact FastAPI application](fastapi-minimal.md).

This application caches product descriptions and ordered product pages for two tenants. FastAPI's [application lifespan](https://fastapi.tiangolo.com/advanced/events/) owns one asyncio MongoDB client and cache manager, and request dependencies supply a catalogue repository and an authenticated principal.

The application's authentication dependency rejects requests by default. The self-check installs [demonstration dependency overrides](https://fastapi.tiangolo.com/advanced/testing-dependencies/) for Alice, who can edit the north tenant's products, and Bob, who can only read the south tenant's products. These identities are for demonstration only. Supply your application's [trusted authentication dependency](https://fastapi.tiangolo.com/tutorial/security/get-current-user/) when adopting the example. Tenant selectors in requests cannot replace the principal's tenant, and cached documents do not grant write permission.

PATCH writes through PyMongo and reads its response directly using a causally consistent session and majority read/write concerns. That response can observe the acknowledged update without waiting for cache invalidation. Direct reads do not refresh cached content; later GETs can return preceding descriptions until invalidation arrives. Inventory commitments, payments, and immediate authorization decisions require their own database consistency controls; see [consistency limits](../usage/consistency.md).

Pages have a bounded size and stable ordering, and their cursors are fully materialized before responding. Delivering a page successfully does not guarantee cache admission. See [cached cursor consumption and limit reuse](../usage/cached-reads.md) and [capacity controls](../reference/api.md#limits).

Large offsets increase the database work required by `skip()`. For large catalogues, prefer [indexed range queries for pagination](https://www.mongodb.com/docs/manual/reference/method/cursor.skip/#using-range-queries).

Run `uv run examples/fastapi_catalogue_example.py` from the repository checkout. The program uses FastAPI's in-process HTTP client to exercise startup, tenant isolation, rejected writes, update responses, and shutdown for each deployment described in [feature-flagged rollout](#feature-flagged-rollout). With caching enabled, it also checks repeated item/page cache hits and eventual invalidation within five seconds, requiring cache hits for both updated responses. This deadline is a self-check limit, not a freshness guarantee. No external HTTP server is needed. The run resets and cleans up `client_query_cache_example_fastapi_catalogue`; use a disposable MongoDB deployment. See the [example catalogue](index.md) for prerequisites and connection settings.

## Feature-flagged rollout

The application chooses direct PyMongo or cached content reads once at startup. Pass the flag from your deployment configuration; it defaults to direct reads, and requests cannot change it:

```python
app = create_app(content_cache_enabled=True)
```

Restart the application to change the flag. Identity and permission checks run before storage access in both modes, and writes and PATCH responses always read directly.

Direct content reads use the primary with majority read concern. With caching enabled, an eligible miss also reads at majority concern, while a hit returns a stored result without running the query on the server. A hit can return a preceding description until invalidation arrives, and cached reads go to the server whenever the database's change stream is unavailable. Neither mode promises the other's freshness or availability; see [consistency](../usage/consistency.md) and [bypass conditions](../reference/api.md#bypass-conditions).

With caching disabled, the application still opens a manager, but the manager starts no change stream and stores no entries. A deployment that never caches can omit the manager; see [rollback to plain PyMongo](../reference/api.md#rollback-to-plain-pymongo). Switching modes requires no data migration.

The self-check starts three deployments over the same data: direct, cached, then direct again. It reports manager snapshots at each boundary and requires a miss followed by hits, a bypass for a session-bound read, unchanged counters for direct reads, and released cache resources after each shutdown. The final direct deployment reads the update made while caching was enabled. To export the same counters, see [OpenTelemetry metrics](../operations/monitoring.md#opentelemetry-metrics). Alert thresholds and rollout percentages belong to your operating policy.

## Running several workers

To serve the catalogue over HTTP with several worker processes, run this command from the repository checkout:

```console
CONTENT_CACHE_ENABLED=true uv run examples/fastapi_catalogue_example.py --serve --workers 2 --port 8000
```

[Uvicorn](https://uvicorn.dev/deployment/) starts the requested number of worker processes, and each one builds the application itself. The cache flag therefore comes from the `CONTENT_CACHE_ENABLED` environment variable: `true` caches content reads, and `false`, the default, reads directly. Each worker's lifespan creates its own client and manager and prints its process ID when the manager starts. When you stop the server with Ctrl+C, each worker closes its manager before its client.

This launch mode gives every worker an independent cache and change stream. It does not use `SharedCacheManager`. See [multi-worker servers](../operations/deployment.md#multi-worker-servers) for the memory and change-stream cost. The served application keeps its authentication dependency, so it answers every request with 401 until you supply your trusted one.

## Complete program

The code below is included from the [canonical Python source](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/fastapi_catalogue_example.py).

<!-- fmt:off -->

```python
--8<-- "examples/fastapi_catalogue_example.py"
```

<!-- fmt:on -->
