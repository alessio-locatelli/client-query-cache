# Changelog

## Unreleased

<!-- Describe final behavior once, one line per change. -->

- `find_one` caches deterministic filters and missing results, with explicit sorting and collation support in synchronous and asyncio views.

- `CacheManager.cached(collection)` returns a cached read view of your own PyMongo collection; call writes and other PyMongo methods on that collection or on `.raw`, since cached views no longer forward them.
- Runnable examples in `examples/` show how to add the cache to real MongoDB-backed libraries, starting with requests-cache.
- `causal_boundary(session)` and `wait_for_invalidations(database, boundary, timeout=...)` let an application wait, with a deadline, until cached reads reflect its own majority-acknowledged write.

## [0.1.0] - 2026-09-30

- Initial release of `client-query-cache`.
