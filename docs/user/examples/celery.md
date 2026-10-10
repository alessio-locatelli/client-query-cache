# Celery integration

The adapter shares the manager's PyMongo client with Celery's MongoDB result backend and routes task metadata reads through a cached `find_one`. Celery still stores results through its raw MongoDB collection.

The program repeatedly polls an unfinished task with `cache=False`, disabling Celery's own result cache so that the MongoDB read cache is observable. It then stores a successful result and polls until the change-stream invalidation exposes the completed task and decoded result. Until then, a cached poll can still report the task as unfinished. Applications that must act on completion immediately should read task state without the cache; see [consistency](../usage/consistency.md#read-after-write). The program exercises the backend directly; it does not need a broker or worker.

See the [example catalogue](index.md) for prerequisites, run commands, expected evidence, and the database-reset warning.

## Complete program

The code below is included from the [canonical Python source](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/celery_example.py).

<!-- fmt:off -->

```python
--8<-- "examples/celery_example.py"
```

<!-- fmt:on -->
