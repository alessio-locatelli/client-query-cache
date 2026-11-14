# cachier integration: sync and asyncio

[cachier](https://pypi.org/project/cachier/4.2.0/) stores a function's return value so repeated calls with the same arguments avoid repeating the calculation. `client-query-cache` caches MongoDB reads, so looking up that stored return value can also avoid a database round trip.

These programs calculate a sales report from MongoDB orders. The first call adds up sales for the North region; subsequent calls reuse cachier's stored report. A small collection adapter connects the two libraries through cachier's public `mongetter` argument. Its `find_one` uses a retained cached collection; writes, deletion, and index operations use the original PyMongo collection. cachier keeps control of its lookup filters and serialization.

Each program reuses one client, process-local manager, and adapter. The asyncio version uses `AsyncMongoClient`, the asynchronous manager, an async `mongetter`, and `await report.aclear_cache()`. Each manager closes before its client. See [manager selection](../getting-started/choose-a-manager.md) for other deployment choices.

## Run either program

Use a [repository checkout](https://github.com/alessio-locatelli/client-query-cache) on a supported [Python and platform configuration](../getting-started/installation.md#requirements), with [uv](https://docs.astral.sh/uv/) available. MongoDB must meet the same requirements, including a replica set or sharded cluster. Follow [Local MongoDB](../getting-started/installation.md#local-mongodb) to start the repository's disposable replica set.

Run from the repository root, without editing the source:

```console
uv run examples/cachier_example.py
uv run examples/cachier_async_example.py
```

Each script declares `cachier[mongo]>=4.2.0` and uses the working-tree `client-query-cache` package. uv resolves the published cachier package into a separate script environment; no local cachier checkout is needed.

`MONGODB_URI` selects the server and defaults to `mongodb://localhost:27017/?directConnection=true`. Set it in your environment to use another disposable deployment.

> **Disposable databases:** Every run resets its entire dedicated database: `client_query_cache_example_cachier` for sync, or `client_query_cache_example_cachier_async` for asyncio. Do not keep valuable data in these databases.

## What to expect

The programs check their values and fail with an explicit message if cache warm-up or invalidation exceeds ten seconds. Successful output includes:

```text
initial North sales: EUR 200
repeated calls: 1 calculation, <positive count> query-cache hits
updated North sales: EUR 220; calculations: 2
invalidation observed after: <elapsed> ms
```

The hit count and elapsed time vary. Repeated calls reuse one calculation and produce MongoDB query-cache hits. The program then changes an order from EUR 80 to EUR 100. Changing source orders alone does **not** expire the stored report: cachier controls function-result expiry and clearing. Clearing removes the stored report, and the program waits until a call recalculates the EUR 220 total.

Clearing does **not** guarantee immediate freshness. A process-local lookup may return the previous report until change-stream invalidation arrives. See [consistency limits](../usage/consistency.md) before adapting this pattern to an application that requires fresh reads.

Use this pattern for calculations that tolerate stale reads and are safe to repeat without unwanted side effects (idempotent calculations). The adapter also caches cachier's calculation status. With independent managers, stale status can cause duplicate calculations or, in the synchronous path, unnecessary waiting. Do not rely on it for strict coordination between workers. In [cachier 4.2.0](https://github.com/python-cachier/cachier/blob/v4.2.0/src/cachier/core.py#L421-L590), synchronous calls can wait for an ongoing calculation; asyncio calls recalculate rather than use that wait path, and do not honor `wait_for_calc_timeout`. These programs check sequential calls only.

The demonstrated benefit comes from repeated reads between storage writes. cachier's default lookup index is non-unique, so a write to any stored result in the same collection invalidates these cached lookups, including unrelated reports. Frequent storage writes can therefore reduce query-cache reuse. See [single-document reads](../reference/api.md#single-document-reads) for the library's invalidation rules.

> **Trust cache writers:** cachier's MongoDB storage serializes return values with pickle. Only trusted writers should have access to that storage; loading a malicious pickle can execute code.

## Complete synchronous program

The code is included from the [canonical Python source](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/cachier_example.py).

<!-- fmt:off -->

```python
--8<-- "examples/cachier_example.py"
```

<!-- fmt:on -->

## Complete asyncio program

The code is included from the [canonical Python source](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/cachier_async_example.py).

<!-- fmt:off -->

```python
--8<-- "examples/cachier_async_example.py"
```

<!-- fmt:on -->
