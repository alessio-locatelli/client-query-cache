# Changelog

## Unreleased

### Bug fixes

- Cached `count_documents()` preserves explicit options and native PyMongo/MongoDB errors in synchronous and asyncio views. Omitted `skip` and `skip=0` share cached counts.
- Reads inside PyMongo `session.bind()` contexts bypass caching in synchronous and asyncio views, preserving transaction visibility and native session validation. Reads also bypass caching when their session cannot be determined.

### Features

- **Breaking:** Cached `find()` and `aggregate()` return native PyMongo cursor subclasses. Call asyncio `find()` without `await` and consume results through the cursor.
- Streaming reads populate the cache only after full consumption and within configured cache limits. Requests with cursor-only options execute through PyMongo without caching.

### Improved documentation

- Add guides for the latest release and development branch, including tutorials, integration examples, and local replica-set setup.

## [0.2.0] - 2026-10-02

### Features

- Export `CacheConfigurationError`, `CacheClosedError`, `UnsupportedCacheRequestError`, and their `CacheError` base class from `client_query_cache`.
- Add manager snapshots for cache statistics, bypass reasons, stream health, and stream costs. The optional OpenTelemetry integration accepts managers and exports a separate bypass-reason counter.
- `find_one()` caches deterministic filters and missing results, with explicit sorting and collation support in synchronous and asyncio views.
- **Breaking:** `CacheManager.cached(collection)` returns a cached read view of your own PyMongo collection. Call writes and other PyMongo methods on that collection or on `.raw`.

### Improved documentation

- Add searchable documentation with mobile navigation and light/dark themes.
- Runnable examples in `examples/` show how to add the cache to real MongoDB-backed libraries, starting with requests-cache.

## [0.1.0] - 2026-09-30

- Initial release of `client-query-cache`.
