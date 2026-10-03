# Consistency

Invalidation is asynchronous. A cached read running concurrently with a write can return the preceding value until the manager processes the corresponding change-stream event. After processing that event, affected results are invalidated; a later read fetches a fresh result or uses a subsequently admitted one. The cache provides no per-write catch-up barrier.

## Read after write

For a read that must immediately observe a preceding write, use the PyMongo collection with the session and read/write concerns appropriate to your application:

```python
collection.update_one({"_id": "book"}, {"$set": {"price": 12}})
current_product = collection.find_one({"_id": "book"})
```

A session-bound read through the cached view also bypasses caching. Direct and session-bound reads do not refresh the cache or synchronize other managers. See [bypass conditions](../reference/api.md#bypass-conditions) and [PyMongo's documentation](https://pymongo.readthedocs.io/) for driver consistency controls.

## Manager isolation

Each manager has its own cache and change streams. Managers in the same process, and managers in different worker processes, share neither cached values nor stream progress. A stream reported as healthy can still have an independent writer's event in flight. See [capacity estimation](../operations/deployment.md#capacity-estimation) and [stream health](../operations/monitoring.md#bypass-reasons-and-stream-health).

During a stream interruption, reads bypass the cache. If the stream cannot resume from its saved position, the affected database's cached data is cleared before reopening. See [recovery](../operations/deployment.md#recovery-behavior).

## Freshness and authorization

Choose raw reads for authorization decisions that require current policy on every request. An unrelated permission change does not invalidate a cached document. See [security boundaries](../operations/deployment.md#security).

The [py-abac example](../examples/py-abac.md) demonstrates eventual policy invalidation, with a polling loop that waits to observe a change. Applications requiring stronger guarantees must use appropriate direct reads.

For maintainers, the [development decision source](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/decisions/defer-causal-invalidation-barrier.md) records why a public invalidation barrier is deferred. Its [research source](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/research/causal-invalidation-barrier.md) preserves the investigated mechanism and limitations.
