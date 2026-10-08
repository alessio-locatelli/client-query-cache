# FastAPI catalogue

This application caches product descriptions and ordered product pages for two tenants. FastAPI's [application lifespan](https://fastapi.tiangolo.com/advanced/events/) owns one asyncio MongoDB client and cache manager, and request dependencies supply a catalogue repository and an authenticated principal.

The application's authentication dependency rejects requests by default. The self-check installs [demonstration dependency overrides](https://fastapi.tiangolo.com/advanced/testing-dependencies/) for Alice, who can edit the north tenant's products, and Bob, who can only read the south tenant's products. These identities are for demonstration only. Supply your application's [trusted authentication dependency](https://fastapi.tiangolo.com/tutorial/security/get-current-user/) when adopting the example. Tenant selectors in requests cannot replace the principal's tenant, and cached documents do not grant write permission.

PATCH writes through PyMongo and reads its response directly using a causally consistent session and majority read/write concerns. That response can observe the acknowledged update without waiting for cache invalidation. Direct reads do not refresh cached content; later GETs can return preceding descriptions until invalidation arrives. Inventory commitments, payments, and immediate authorization decisions require their own database consistency controls; see [consistency limits](../usage/consistency.md).

Pages have a bounded size and stable ordering, and their cursors are fully materialized before responding. Delivering a page successfully does not guarantee cache admission. See [cached cursor consumption and limit reuse](../usage/cached-reads.md) and [capacity controls](../reference/api.md#limits).

Large offsets increase the database work required by `skip()`. For large catalogues, prefer [indexed range queries for pagination](https://www.mongodb.com/docs/manual/reference/method/cursor.skip/#using-range-queries).

Run `uv run examples/fastapi_catalogue_example.py` from the repository checkout. The program uses FastAPI's in-process HTTP client to exercise startup, tenant isolation, rejected writes, repeated item/page cache hits, update responses, eventual invalidation within a five-second check, and shutdown. It requires cache hits for both updated responses. This deadline is a self-check limit, not a freshness guarantee. No external HTTP server is needed. The run resets and cleans up `client_query_cache_example_fastapi_catalogue`; use a disposable MongoDB deployment. See the [example catalogue](index.md) for prerequisites and connection settings.

## Complete program

The code below is included from the [canonical Python source](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/fastapi_catalogue_example.py).

<!-- fmt:off -->

```python
--8<-- "examples/fastapi_catalogue_example.py"
```

<!-- fmt:on -->
