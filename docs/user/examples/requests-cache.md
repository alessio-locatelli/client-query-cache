# requests-cache integration

The adapter routes requests-cache's MongoDB storage lookups through `CacheManager`, while its writes, deletion, and index management use the original PyMongo collections. It converts the cached `find` list into the iterator expected by requests-cache.

The program serves HTTP locally, fetches a response once, and checks that repeated storage reads hit this library's cache without another origin request. Deleting the stored response uses raw writes; the program waits for invalidation before checking that the next request reaches the origin again. This separates requests-cache's HTTP response behavior from the MongoDB read cache.

See the [example catalogue](index.md) for prerequisites, run commands, expected evidence, and the database-reset warning.

## Complete program

The code below is included from the [canonical Python source](https://github.com/alessio-locatelli/client-query-cache/blob/main/examples/requests_cache_example.py).

<!-- fmt:off -->

```python
--8<-- "examples/requests_cache_example.py"
```

<!-- fmt:on -->
