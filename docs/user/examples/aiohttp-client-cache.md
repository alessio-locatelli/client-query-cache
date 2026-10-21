# aiohttp-client-cache integration

This adapter uses process-local `CacheManager` for its broader cached-read coverage. See [manager selection](../getting-started/choose-a-manager.md) for shared identity-read deployments.

The adapter shares the async manager's PyMongo client with aiohttp-client-cache's MongoDB backend. Response and redirect lookups use cached reads; storage writes and other operations keep their upstream behavior. The response storage uses upstream pickle serialization. Restrict database writes to trusted application processes: loading a tampered response can execute code. See [Python's pickle security guidance](https://docs.python.org/3/library/pickle.html).

The program serves JSON from an in-process aiohttp origin, waits for the stored response’s change event before measuring repeated storage cache hits, deletes the stored response, and waits for change-stream invalidation before fetching from the origin again. It checks that the origin received exactly two requests and closes the session, server, manager, and client.

See the [example catalogue](index.md) for prerequisites, run commands, expected evidence, and the database-reset warning.

## Complete program

The code below is included from the [canonical Python source](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/aiohttp_client_cache_example.py).

<!-- fmt:off -->

```python
--8<-- "examples/aiohttp_client_cache_example.py"
```

<!-- fmt:on -->
