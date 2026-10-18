# Consistency

Both managers invalidate asynchronously through MongoDB change streams. A cached read can return the value from before a write even after the write has returned. Once the relevant event is processed, affected entries are invalidated; a later read fetches or reuses a subsequently admitted result. There is no per-write catch-up barrier or guaranteed invalidation delay.

Eligible misses use primary, majority reads, including when read concern is unspecified. Direct PyMongo reads use the collection's chosen concern, normally the deployment default. Majority admission keeps data that could roll back out of the cache; it does not make hits current. See [read profiles and bypass conditions](../reference/api.md#bypass-conditions).

## Read after write

Read through PyMongo when an operation must observe a preceding write, with the session and concerns appropriate to the application. For example, on a supported replica set:

```python
from pymongo.read_concern import ReadConcern
from pymongo.write_concern import WriteConcern

consistent_products = collection.with_options(
    read_concern=ReadConcern("majority"), write_concern=WriteConcern(w="majority")
)
with client.start_session(causal_consistency=True) as session:
    consistent_products.update_one(
        {"_id": "book"}, {"$set": {"price": 12}}, session=session
    )
    current_product = consistent_products.find_one({"_id": "book"}, session=session)
```

The [FastAPI examples](../examples/index.md) show direct write responses alongside cached content reads. Passing a session to a cached view, or reading inside `session.bind()`, bypasses caching, including in transactions. Passing `session=None` inside a bound context still uses the bound session. If the driver cannot determine the effective session, the cache bypasses. See [PyMongo sessions](https://pymongo.readthedocs.io/en/stable/api/pymongo/client_session.html#pymongo.client_session.ClientSession.bind).

Direct and session-bound reads do not populate or refresh cached entries and do not synchronize other managers. A successful direct response therefore does not make a subsequent cached GET current.

## Manager isolation

Each **process-local `CacheManager`** owns an independent cache and streams. Even managers in the same process warm independently and can process an event at different times.

**`SharedCacheManager` workers attached to the same server** reuse stored values and the owner's stream progress. Separate servers remain independent. Sharing removes duplicate cache state, not the delay between MongoDB committing a write and the owner processing its event. See [manager selection](../getting-started/choose-a-manager.md).

While a stream is unavailable, reads bypass caching. If saved stream history is lost, the affected database's cached data is cleared before reopening. Shared managers also stop serving hits after the owner's [progress-expiry safeguard](../operations/shared-cache.md#consistency-and-recovery) fires. A healthy stream or a shared hit does not establish that the latest write has arrived.

## Cursor snapshots

With either manager, a hit cursor keeps one isolated result snapshot after consumption starts. Later invalidation, stream interruption or manager closure does not replace its remaining documents. Start a new query for a new lookup. Miss results are admitted only after successful complete consumption and only if they remain valid. See [cached cursor contracts](../reference/api.md#cached-read-methods) and [shared reads](../reference/shared-cache.md#worker-managers-and-reads).

Hits skip server execution. They cannot reproduce fresh query errors, network errors or query effects; use `.raw` when execution itself matters.

## Freshness and authorization

Use direct reads for authorization decisions that require current policy. Credential or role changes alone do not invalidate cached documents. See [shared security](../operations/shared-cache.md#security-and-monitoring) and [process-local security](../operations/deployment.md#security).

The [py-abac example](../examples/py-abac.md) demonstrates eventual policy invalidation, not immediate re-authorization. The [maintainer decision](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/decisions/defer-causal-invalidation-barrier.md) records the constraints on adding a public invalidation barrier.
