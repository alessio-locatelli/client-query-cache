# Proposal

## Why

The public example calls PyMongo writes on `CachedCollection`, but those methods exist only through an `Any`-returning `__getattr__` proxy. An IDE cannot navigate to `insert_one`, `drop`, or other proxied methods, and a type checker cannot validate their arguments. This makes ordinary collection work harder to use and easier to misuse.

## What Changes

- **BREAKING**: Make PyMongo's own collection and database objects the documented targets for writes, administration, and uncached operations. Expose cached reads through a separate, explicitly typed collection view obtained from an existing PyMongo collection.
- **BREAKING**: Remove generic method delegation from cached collection and database views. Unsupported methods must be reached through a real PyMongo object, so the cache view cannot silently erase PyMongo signatures or IDE navigation.
- Preserve the six cache-aware read operations, raw-object access, caller-owned client lifetime, synchronous and asyncio parity, and cache coherence behavior.
- Update usage guidance and examples to show the raw collection and its cached read view together, using `cache_manager` as the example variable. Keep the existing manager indexing path for cached reads and a direct path to its raw object.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cached-read-api`: Define the explicit cached-read view, typed PyMongo access, and the boundary between cache-aware reads and direct PyMongo operations.

## Impact

The public collection/database facade API changes in both `src/client_query_cache/synchronous/` and `src/client_query_cache/asynchronous/`. Direct calls such as `cache_manager["db"]["collection"].insert_one(...)` in this repository must move to the caller's PyMongo collection or the view's `.raw` property. There are no real users yet, so the README and API reference will describe only the resulting interface; one Unreleased changelog entry will record the change without a public migration guide. No new dependency, MongoDB request, cache store, or change-stream owner is introduced.
