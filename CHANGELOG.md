# Changelog

## Unreleased

- Reads inside PyMongo `session.bind()` contexts bypass caching in synchronous and asyncio views, preserving transaction visibility and native session validation. Reads also bypass caching when their effective session cannot be determined.
- Provide documentation for the latest release and development branch, including tutorials, integration examples, and local replica-set setup.

## [0.2.0] - 2026-10-02

- Export `CacheConfigurationError`, `CacheClosedError`, `UnsupportedCacheRequestError`, and their `CacheError` base class from `client_query_cache`.
- Provide searchable documentation with mobile navigation, light/dark themes, and local preview/build commands.
- The development container installs DNF packages from Fedora 44 repositories while retaining the Node.js 24 track.
- Add local manager snapshots for cache statistics, fixed bypass reasons, stream health, and stream costs; accept managers in the optional OpenTelemetry bridge and export a separate bypass-reason counter.
- `find_one` caches deterministic filters and missing results, with explicit sorting and collation support in synchronous and asyncio views.
- `CacheManager.cached(collection)` returns a cached read view of your own PyMongo collection; call writes and other PyMongo methods on that collection or on `.raw`, since cached views no longer forward them.
- Runnable examples in `examples/` show how to add the cache to real MongoDB-backed libraries, starting with requests-cache.

## [0.1.0] - 2026-09-30

- Initial release of `client-query-cache`.
