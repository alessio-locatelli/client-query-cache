# Changelog

## Unreleased

<!-- Describe final behavior once, one line per change. -->

- `CacheManager.cached(collection)` returns a cached read view of your own PyMongo collection; call writes and other PyMongo methods on that collection or on `.raw`, since cached views no longer forward them.
- Runnable examples in `examples/` show how to add the cache to real MongoDB-backed libraries, starting with requests-cache.

## [0.1.0] - 2026-09-30

- Initial release of `client-query-cache`.
