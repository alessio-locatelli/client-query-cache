# Selective invalidation

Normally, a write invalidates cached `find()` and `count_documents()` results for
its collection. Selective invalidation lets those results stay cached when the
write can be shown not to affect them.

Consider it for frequently read author feeds and counts in a collection receiving
writes for many authors: an insert for one author need not invalidate another
author's results.

## Configure a collection

The synchronous example assumes `client` is an existing PyMongo `MongoClient`
connected to a supported MongoDB deployment. For client and deployment setup, see
the [synchronous quick start](../getting-started/synchronous.md) or
[asyncio quick start](../getting-started/asyncio.md).

Configure the collection when creating its process-local manager:

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

For asyncio, run this inside an async function with an existing PyMongo
`AsyncMongoClient` as `client`. Use the asynchronous manager and await cursor
consumption and counts:

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

## Which results stay cached

For the examples above, with both options enabled and simple collation, these
writes have the following effects after their change events have been processed:

| Write to `blog.posts`        | Cached author feed | Cached author count |
| ---------------------------- | ------------------ | ------------------- |
| Insert with `author_id=99`   | Preserved          | Preserved           |
| Insert with `author_id=42`   | Invalidated        | Invalidated         |
| Update only `views`          | Invalidated        | Preserved           |
| Update `published`           | Invalidated        | Invalidated         |
| Replace or delete a document | Invalidated        | Invalidated         |

Enable either option independently. Insert partitioning lets a supported author
feed or count survive inserts for other authors. Count dependencies let a count
survive updates to unrelated fields, such as a change to `views` when the query
depends only on `author_id` and `published`. Updates still invalidate feeds.
Index hints disable count retention through updates, while a separately supported
insert partition can still protect that count.

## Costs and limitations

Selective invalidation is not automatically faster. It adds MongoDB and application
processing and extra event data to the existing change stream in exchange for
fewer database reads. It can help with expensive counts or large feeds that are
read frequently between unrelated writes. Mostly matching writes or infrequent
reads offer less opportunity to recover that extra cost.

Compare policies enabled and disabled with your queries, document sizes, and write
rates. Use the [eligibility exercise](eligibility.md) to check that your reads are
being cached, then [monitoring](../operations/monitoring.md) to compare hit rate,
request latency, application and MongoDB CPU, memory, and stream activity.

When a write cannot be shown to be irrelevant, cached results are invalidated as
usual. Unsupported cases can still be cached if otherwise eligible. If the manager
has no room to track an additional query for selective caching, that query uses
normal collection-wide invalidation.
See the [API reference](../reference/api.md#selective-invalidation)
for supported query shapes, bounds, and fallback rules. Other read methods retain
their existing behavior; writes and administration use `.raw` or the original
PyMongo handles. `SharedCacheManager` does not accept these policies.

The existing [eventual-consistency contract](consistency.md) applies. Selective
retention adds no read-after-write barrier: a cached read can still precede
processing of a relevant event. Use direct PyMongo reads when fresh server
execution is required.
