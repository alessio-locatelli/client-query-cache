# Eve integration

The Mongo data-layer subclass shares the manager's client with an Eve application. Its collection receiver caches `find`, `find_one`, and `count_documents` during GET/HEAD requests. Mutation precondition checks and operations without an HTTP request context use raw PyMongo reads. Eve retains its query construction, validation, writes, and response formatting. The example configures one database and ordinary document resources.

The program uses Eve's in-process application client to create items for two owners. It checks sorting, pagination, projection, owner filtering, and response metadata during repeated page and item GETs, then sends two consecutive PATCHes using each response's ETag. It verifies that mutations perform no cached reads, then waits until both GETs observe the final change. The resource uses majority write concern so that acknowledged setup writes are visible to the cache's majority reads.

Cached authorization filters can return preceding values until invalidation is processed. Use raw reads when authorization requires current policy on every request; see [consistency limits](../usage/consistency.md).

See the [example catalogue](index.md) for prerequisites, run commands, expected evidence, and the database-reset warning.

## Complete program

The code below is included from the [canonical Python source](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/eve_example.py).

<!-- fmt:off -->

```python
--8<-- "examples/eve_example.py"
```

<!-- fmt:on -->
