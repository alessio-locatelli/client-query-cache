# Consistency

Invalidation is asynchronous. A cached read can return the value from before a write, even after the write has returned, until the manager processes the corresponding change-stream event. After processing that event, affected results are invalidated; a later read fetches a fresh result or uses a subsequently admitted one. The cache provides no per-write catch-up barrier.

A hit cursor retains one result snapshot after consumption starts. A later write or stream interruption does not replace its remaining documents; a new execution checks current invalidation and stream health. Misses are admitted only after complete consumption and only if their invalidation guards remain valid. Eligible misses read from the primary with `majority` read concern, even when read concern is unspecified, so the cache admits only majority-committed results without making hits current; see [bypass conditions](../reference/api.md#bypass-conditions). Hits skip query execution and therefore cannot reproduce fresh server/network errors or query effects.

## Read after write

For a read that must immediately observe a preceding write, use the PyMongo collection with the session and read/write concerns appropriate to your application:

```python
collection.update_one({"_id": "book"}, {"$set": {"price": 12}})
current_product = collection.find_one({"_id": "book"})
```

A read through the cached view bypasses caching when you pass a session or call it inside `session.bind()`, including inside a transaction. Passing `session=None` inside a bound context still uses that context's session. Direct and session-bound reads do not refresh the cache or synchronize other managers. See [bypass conditions](../reference/api.md#bypass-conditions) and [PyMongo's session documentation](https://pymongo.readthedocs.io/en/stable/api/pymongo/client_session.html#pymongo.client_session.ClientSession.bind) for driver consistency controls.

## Manager isolation

Each manager has its own cache and change streams. Managers in the same process, and managers in different worker processes, share neither cached values nor stream progress. A stream reported as healthy can still have an independent writer's event in flight. See [capacity estimation](../operations/deployment.md#capacity-estimation) and [stream health](../operations/monitoring.md#bypass-reasons-and-stream-health).

During a stream interruption, reads bypass the cache. If the stream cannot resume from its saved position, the affected database's cached data is cleared before reopening. See [recovery](../operations/deployment.md#recovery-behavior).

## Freshness and authorization

Choose raw reads for authorization decisions that require current policy on every request. An unrelated permission change does not invalidate a cached document. See [security boundaries](../operations/deployment.md#security).

The [py-abac example](../examples/py-abac.md) demonstrates eventual policy invalidation, with a polling loop that waits to observe a change. Applications requiring stronger guarantees must use appropriate direct reads.

For maintainers, the [development decision source](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/decisions/defer-causal-invalidation-barrier.md) records why a public invalidation barrier is deferred. Its [research source](https://github.com/alessio-locatelli/client-query-cache/blob/main/docs/development/research/causal-invalidation-barrier.md) preserves the investigated mechanism and limitations.

If the installed driver cannot determine the effective session needed
by the cache, reads execute through native PyMongo without caching.
