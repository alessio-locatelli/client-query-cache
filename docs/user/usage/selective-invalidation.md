# Selective invalidation

Use selective invalidation when repeated feeds or counts lose useful cache entries
to writes that cannot affect their results. Configure the collection when creating
its process-local manager:

```python
from client_query_cache import CacheManager, SelectiveInvalidation

with CacheManager(
    client,
    invalidation={
        ("blog", "posts"): SelectiveInvalidation(
            insert_partition_field="author_id",
            update_dependencies_for_counts=True,
        )
    },
) as manager:
    posts = manager["blog"]["posts"]
    query = {"author_id": 42, "published": True}
    feed = posts.find(query).sort("_id", -1).limit(20).to_list()
    count = posts.count_documents(query)
```

With asyncio, use the asynchronous manager and await consumption and counts:

```python
from client_query_cache.asynchronous import CacheManager, SelectiveInvalidation

async with CacheManager(
    client,
    invalidation={
        ("blog", "posts"): SelectiveInvalidation(
            insert_partition_field="author_id",
            update_dependencies_for_counts=True,
        )
    },
) as manager:
    posts = manager["blog"]["posts"]
    query = {"author_id": 42, "published": True}
    feed = await posts.find(query).sort("_id", -1).limit(20).to_list()
    count = await posts.count_documents(query)
```

Enable either option independently. Insert partitioning lets a supported author
feed or count survive inserts for other authors. Count dependencies let a count
survive updates to unrelated fields, such as a change to `views` when the query
depends only on `author_id` and `published`. Updates still invalidate feeds.
Index hints disable count retention through updates, while a separately supported
insert partition can still protect that count.

These policies add server-side work and bounded hint payloads to the collection's
existing database stream. They can pay off when unrelated writes frequently
invalidate repeatedly read results, particularly expensive counts or large feeds.
For mostly matching writes or infrequent reads, ordinary invalidation avoids this
additional work. Measure with your queries, document sizes, and write rates.

Unproved cases use conservative invalidation and retain ordinary cache eligibility.
If selective capacity is occupied, new reads use ordinary guards until capacity
becomes available. See the [API reference](../reference/api.md#selective-invalidation)
for supported query shapes, bounds, and fallback rules. Other read methods retain
their existing behavior; writes and administration use `.raw` or the original
PyMongo handles. `SharedCacheManager` does not accept these policies.

The existing [eventual-consistency contract](consistency.md) applies. Selective
retention adds no read-after-write barrier: a cached read can still precede
processing of a relevant event. Use direct PyMongo reads when fresh server
execution is required.
