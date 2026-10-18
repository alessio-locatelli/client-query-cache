# Changelog

<!--
This changelog is for users upgrading the PyPI package.
Before adding an entry, ask: "If this were the sole changelog entry, would
publishing a new package to PyPI be warranted?" If no, omit the entry.
Describe the final effect on package users once, without review history.
Exclude internal refactoring, CI,
development tooling, tests/coverage, documentation publishing, OpenSpec
completion, and coding-agent achievements. Put internal rationale in commit
bodies or OpenSpec. An empty Unreleased section is valid.
-->

## Unreleased

## [0.9.0] - 2026-10-18

### Features

- Share eligible filtered reads, cursor results, aggregations, counts and distinct values across sync and asyncio workers with `SharedCacheManager`.

### Performance

- Reduce CPU and latency overhead for `find()` cache misses.

## [0.8.1] - 2026-10-17

### Performance

- Reduce CPU overhead for cache misses and reads by `_id`.

## [0.8.0] - 2026-10-15

### Features

- Share cached `find_one()` reads by `_id` and database change streams across trusted sync and asyncio workers on one host with `SharedCacheServer` and `SharedCacheManager`. The server owns startup, shutdown and restart; workers retain their own PyMongo clients and fall back to direct reads during owner outages.
- **Breaking:** The distribution includes a Rust native module. Wheels support CPython 3.14+ on Linux x86-64 with glibc 2.28+; shared caching requires Linux 5.1+ with `memfd` sealing. Source builds require Rust and Cargo. Free-threaded Python and other platforms are outside this release's supported contract.

## [0.7.0] - 2026-10-11

### Bug fixes

- A cached `find_one()` by `_id` no longer keeps returning an outdated document after writes to a matching document whose stored `_id` is a numerically equal decimal, such as `Decimal128("1")` for a read by `1`, including inside an embedded `_id` document.
- Cache budgets and lag-window counts reject non-integer values, including NaN, infinities, booleans, and integer subclasses, with `CacheConfigurationError` at configuration construction.
- MongoDB Search, Vector Search, and `$listSearchIndexes` aggregations through cached views run with the caller's read concern instead of failing.
- `$near`, `$nearSphere`, and `$geoNear` reads, reads that reference `$$USER_ROLES`, and `find_one()` and `find()` projections that use `$rand`, `$function`, `$$NOW`, or `$$CLUSTER_TIME` bypass the cache, so they no longer return results that index changes, role changes, or the first execution left stale.

### Performance

- Cached results cost less process memory and CPU: about 210 fewer bytes for each document cached by `_id`, and for other cached results about 70 fewer bytes plus a more compact cache key, for example about 440 fewer bytes for a result cached by a one-field filter and about 950 fewer with a 48-value `$in` filter. Building those cache keys on each read takes about 25–55% less CPU.

### Features

- Cached `find_one()` filters that pin `_id` to an exact value under simple collation now retain their result after writes to other documents, including filters with additional predicates such as `customer_id`.
- **Breaking:** Rename `StreamHealthSnapshot.database_name` to `requested_database_name`. It holds the name you passed to `stream_health_snapshot()`, which is not validated, so while the manager is open an empty or unknown name reports `not_started`.

## [0.6.0] - 2026-10-09

### Bug fixes

- The first `find_one()` whose filter matches a unique index records one cache miss instead of two in manager snapshots and OpenTelemetry metrics, in synchronous and asyncio managers.

## [0.5.0] - 2026-10-08

### Features

- Allow installation on every Python 3.14 patch release.

### Bug fixes

- Failed change-stream startups retry on later reads with a bounded cooldown. Starting one database's stream allows other databases to activate or use their caches; competing reads for the starting database run uncached.
- Manager shutdown waits for pending stream startup and cleanup. Async shutdown releases its resources before propagating cancellation, including repeated cancellation requests.

## [0.4.0] - 2026-10-07

### Features

- **Breaking:** Rename `CacheManager.cached(collection)` to `CacheManager.get_cached_collection(collection)` in synchronous and asyncio managers.
- **Breaking:** Remove `CacheManager.ensure_cache_eligible` and make `cache_ineligibility_reason`, `default_collation_for`, and `unique_keys_for` private.

## [0.3.0] - 2026-10-06

### Bug fixes

- Cached `count_documents()` preserves explicit options and native PyMongo/MongoDB errors in synchronous and asyncio views. Omitted `skip` and `skip=0` share cached counts.
- Reads inside PyMongo `session.bind()` contexts bypass caching in synchronous and asyncio views, preserving transaction visibility and native session validation. Reads also bypass caching when their session cannot be determined.

### Features

- Cached `find()` reuses results across top-level permutations of ordinary scalar equality predicates in synchronous and asyncio views.
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
