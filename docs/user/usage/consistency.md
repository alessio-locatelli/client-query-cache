# Consistency

Both managers invalidate asynchronously through MongoDB change streams. A cached read can return the value from before a write even after the write has returned. Once the relevant event is processed, affected entries are invalidated; a later read fetches or reuses a subsequently admitted result. There is no per-write catch-up barrier or guaranteed invalidation delay. Entries have no time-to-live or age limit, and the API offers no call to invalidate selected entries: change-stream events invalidate them, and capacity limits evict them.

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

When revocation must take effect immediately, check authorization before retrieving or returning cached content. Read policy directly through PyMongo with the read preference, read concern and session settings your application requires. Use direct reads for content that also requires current server-side access checks. See [shared security](../operations/shared-cache.md#security-and-monitoring) and [process-local security](../operations/deployment.md#security).

The [py-abac example](../examples/py-abac.md) demonstrates eventual policy invalidation, not immediate re-authorization. The [maintainer decision](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/decisions/defer-causal-invalidation-barrier.md) records the constraints on adding a public invalidation barrier.

### Rotate credentials or reduce read access

Credential and role changes leave existing cached documents in place. Replace the affected cache deployments when rotating MongoDB credentials or reducing read visibility:

1. Stop accepting affected cached reads. Drain or stop affected workers before serving under the new policy, and discard outstanding cached cursors. Copies already returned remain with their recipients.
2. Close affected managers, then close their MongoDB clients. In a shared deployment, stop all workers attached to the affected server before the parent closes the server. Retire its `SharedCacheConnection` along with it.
3. Create replacement MongoDB clients and managers with the intended credentials and read visibility before resuming traffic. For a shared cache, have the parent start a new `SharedCacheServer` with the intended credentials and database scope before creating the worker managers. Give its new connection only to trusted workers using the same MongoDB deployment and credentials with equivalent read visibility.

`cache_server.restart()` starts with an empty cache and reuses the server's MongoDB configuration and existing attachment credentials. Use a new server for the cutover. The [permission recovery exercise](../operations/permission-recovery.md) shows how an existing manager resumes caching when it gains change-stream access.
