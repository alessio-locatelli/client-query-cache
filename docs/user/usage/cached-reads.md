# Cached reads

Keep a PyMongo handle for writes and administration, and a cached view for repeated reads:

```python
collection = client["shop"]["products"]
cached_products = cache_manager.cached(collection)

collection.update_one({"_id": "book"}, {"$set": {"price": 12}}, upsert=True)
product = cached_products.find_one({"_id": "book"})
```

The collection must come from the manager's own client. See [cached collection views](../reference/api.md#cached-collection-views) for access shortcuts and ownership details. With asyncio, await writes and cached reads using the same arguments.

## Read methods

The cached view provides `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, and `distinct`. These methods either reuse a cached result, fetch and admit a result, or execute directly through PyMongo when the request is ineligible.

`find` and `aggregate` return fully materialized lists, including with asyncio. Use `cached_products.raw.find(...)` for a cursor. Writes and every other PyMongo operation belong on the original collection or `.raw`; the cached view does not expose them. See [method contracts](../reference/api.md#cached-read-methods).

For `count_documents`, omit `skip` and `limit` to count all matching documents. Explicit options are preserved, and native PyMongo/MongoDB errors propagate: `skip=0` is valid, while `limit=0`, `limit=None`, `skip=None`, and `hint=None` raise native errors, including after an unbounded count has been cached.

## Filters, sorting, and collation

Deterministic single-document queries, including compound filters, match-all queries and missing results, can be cached. For example, select the latest active product with explicit string matching:

```python
product = cached_products.find_one(
    {"status": "active"},
    sort=[("updated_at", -1), ("_id", 1)],
    collation={"locale": "en", "strength": 2},
)
```

An exact `_id` lookup or a qualifying unique index can keep its cached result when another document changes. Other eligible queries are refreshed after any write to the collection. See [single-document reads](../reference/api.md#single-document-reads) for sort, collation, projection, index, and decoding rules.

## Why only reads are cached

Writes always go to MongoDB through PyMongo. Once the manager processes a write's change-stream event, it invalidates affected cached results so that the next read fetches them again. This also covers writes by other clients. The cache does not intercept, replay, or populate entries from write responses; many writes do not return the resulting document.

## Uncached fallback

Sessions, incompatible read options, views, time-series collections, unsafe queries and unavailable streams can bypass caching. Oversized results are returned without being cached. Unsupported cursor-only requests raise a cache error and belong on `.raw`. The underlying driver retains its normal errors. See [bypass conditions](../reference/api.md#bypass-conditions), [limits](../reference/api.md#limits), and [errors](../reference/api.md#errors).

Choose cached reads according to the application's [consistency requirements](consistency.md), then measure your [workload](../benchmarks/index.md).
