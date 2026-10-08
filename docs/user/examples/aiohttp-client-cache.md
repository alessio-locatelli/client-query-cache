# aiohttp-client-cache integration

The adapter shares the async manager's PyMongo client with aiohttp-client-cache's MongoDB backend. Response and redirect lookups use cached reads; storage writes and other operations keep their upstream behavior. The response storage inherits upstream pickle serialization.

The program serves JSON from an in-process aiohttp origin, repeats requests to demonstrate storage cache hits, deletes the stored response, and waits for change-stream invalidation before fetching from the origin again. It checks that the origin received exactly two requests and closes the session, server, manager, and client.

See the [example catalogue](index.md) for prerequisites, run commands, expected evidence, and the database-reset warning.

## Complete program

The code below is included from the [canonical Python source](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/aiohttp_client_cache_example.py).

<!-- fmt:off -->

```python
--8<-- "examples/aiohttp_client_cache_example.py"
```

<!-- fmt:on -->
