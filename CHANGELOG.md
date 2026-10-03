# Changelog

## Unreleased

- Preserve previous documentation output when replacement fails and retrieve stable corrections through retained source refs.

<!-- Describe final behavior once, one line per change. -->

- Default documentation to the latest release with a development edition selector, footer navigation, exact caching prerequisites and a local replica-set example.

- Publish complete tutorials and integration examples in a grouped documentation site, with separate development guides and preserved guide bookmarks.

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
