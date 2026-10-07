## Why

`CacheManager` exposes members that users cannot discover or have no use for. `ensure_cache_eligible` has no production caller and no documentation. `cache_ineligibility_reason`, `default_collation_for`, and `unique_keys_for` are wiring between the manager and `CachedCollection`. Each public name is a promise to maintain it. `cached(collection)`, the main entry point, is also named like a predicate and reads as a yes/no question.

## What Changes

- **BREAKING:** Rename `CacheManager.cached(collection)` to `CacheManager.get_cached_collection(collection)` in the synchronous and asyncio managers, with no alias. Update every caller, guide, and example.
- **BREAKING:** Delete `ensure_cache_eligible`, which has no production caller.
- **BREAKING:** Make `cache_ineligibility_reason`, `default_collation_for`, and `unique_keys_for` private (underscore-prefixed) in both managers.
- Keep `client`, `cache_core`, the snapshot methods, `close`, and context-manager support public. The public guides already document them.
- Audit the public members of `CachedDatabase` and `CachedCollection`. All of them are either documented or mirror PyMongo, so nothing changes there.
- Guard the resulting public member sets of `CacheManager`, `CachedDatabase`, and `CachedCollection` with a regression test.
- Add a `CHANGELOG.md` entry.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cached-read-api`: add requirements for the self-describing accessor name and for a documented-or-private public surface on the manager and its cached views.

## Impact

- Code: `src/client_query_cache/{synchronous,asynchronous}/{manager,collection}.py` and the tests that call the renamed or privatized members.
- Docs and examples: `README.md`, `docs/user/`, `examples/`, `research/collection_adapter/live_error.py`, and `tests/e2e/test_installed_package.py`.
- The in-flight `add-real-usage-examples` change cites the old accessor name in its planning artifacts.
- Users of 0.3.0 who call `cached`, `ensure_cache_eligible`, or the other three methods must migrate.
