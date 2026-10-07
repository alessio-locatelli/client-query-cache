# Cached reads

Keep a PyMongo handle for writes and administration, and a cached view for repeated reads:

```python
collection = client["shop"]["products"]
cached_products = cache_manager.get_cached_collection(collection)

collection.update_one({"_id": "book"}, {"$set": {"price": 12}}, upsert=True)
product = cached_products.find_one({"_id": "book"})
```

The collection must come from the manager's own client. See [cached collection views](../reference/api.md#cached-collection-views) for access shortcuts and ownership details. With asyncio, await writes and single-result reads; `find()` returns its async cursor immediately, and `aggregate()` returns its cursor when awaited.

## Read methods

The cached view provides `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, and `distinct`. These methods either reuse a cached result, fetch and admit a result, or execute directly through PyMongo when the request is ineligible.

`find()` and `aggregate()` return native cursor subclasses. Iterate them or materialize explicitly:

```python
with cached_products.find({"status": "active"}).sort("name").limit(10) as cursor:
    for product in cursor:
        print(product)
items = cached_products.find({"status": "active"}).to_list()
```

With asyncio:

```python
async with cached_products.find({"status": "active"}) as cursor:
    async for product in cursor:
        print(product)
items = await cached_products.find({"status": "active"}).to_list()
cursor = await cached_products.aggregate([{"$match": {"status": "active"}}])
first_page = await cursor.to_list(length=10)
remaining = await cursor.to_list()
```

Only complete successful consumption can populate the cache. Close partially consumed cursors you no longer need. A hit that has started keeps its snapshot during later invalidation; use a new execution for a fresh lookup. Explicit find batching and aggregate `batchSize` at invocation bypass caching. A later aggregation cursor `batch_size()` call validates normally and affects future native batches; on a local hit it has no remote effect. Writes and every other PyMongo operation belong on the original collection or `.raw`; the cached view does not expose them. See [method contracts](../reference/api.md#cached-read-methods).

A positive `find()` limit can reuse the prefix of a complete cached result with a larger limit:

```python
products = cached_products.find({"status": "active"}).sort("_id").limit(100).to_list()
first_page = cached_products.find({"status": "active"}).sort("_id").limit(10).to_list()
```

The second read can return the first ten products without a MongoDB read while the source remains valid and cached. With asyncio, await both `to_list()` calls. A fully consumed unlimited query (omitted limit or integer `limit=0`) can also supply a positive-limit prefix. A smaller source cannot serve a larger request, even if it returned fewer documents than its limit. Unlimited, negative, and boolean requests require an exact cached query; negative and boolean sources cannot supply other limits.

All other final query options must match, including filter representation, projection, sort order, skip, collation, collection, and decoding options. Chained options are checked when execution starts. Use a sort with a unique tie-breaker such as `_id` when prefix order matters. Each hit returns an isolated snapshot; changing a returned document does not change later hits. The same [eventual consistency limits](consistency.md) apply to prefixes.

For `count_documents`, omit `skip` and `limit` to count all matching documents. Explicit options are preserved, and native PyMongo/MongoDB errors propagate: `skip=0` is valid, while `limit=0`, `limit=None`, `skip=None`, and `hint=None` raise native errors, including after an unbounded count has been cached.

## Filters, sorting, and collation

`find()` can reuse a cached result when ordinary scalar equality predicates
appear in a different top-level order:

```python
products = (
    cached_products.find({"status": "active", "region": "eu"}).sort("_id").to_list()
)
same_products = (
    cached_products.find({"region": "eu", "status": "active"}).sort("_id").to_list()
)
```

This applies to plain dictionaries with exact built-in string field names not starting with `$` and values
of `None` or built-in bool, int, float, or str types. All other query options
must match; with asyncio, await each `to_list()` call. Document and array values,
operators, regexes, BSON-specific values, and custom forms retain their existing
order-sensitive cache matching. They can still be cached when otherwise
eligible. Document fields and array elements are never reordered. This reuse
rule applies only to `find()`, and MongoDB receives the original filter on a miss.

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

Sessions, incompatible read options, views, time-series collections, unsafe queries and unavailable streams can bypass caching. Oversized results are returned without being cached. Cursor-only requests, including tailable/exhaust/partial-result find and `$changeStream` aggregation, execute natively. Hits skip query execution and cannot reproduce a fresh server error; use `.raw` when execution itself matters. The underlying driver retains its normal errors. See [bypass conditions](../reference/api.md#bypass-conditions), [limits](../reference/api.md#limits), and [errors](../reference/api.md#errors).

Choose cached reads according to the application's [consistency requirements](consistency.md), then measure your [workload](../benchmarks/index.md).
