# Proposal

## Why

`CachedCollection` and `CachedDatabase` currently expose only the six cache-aware read methods plus `.raw`; every other PyMongo method — every write, `find_one_and_update`, index and admin methods — is only reachable through `.raw`, because the facades have no `__getattr__` fallback. This makes `CacheManager` non-swappable: application code written against the cached facade (`collection.raw.insert_one(...)`) breaks if the manager is replaced by a dummy or a `contextlib.nullcontext(client)` stand-in (a plain PyMongo `Collection` has no `.raw`), and code written against a dummy breaks the same way in reverse. Closing that gap means answering "does this method get cached?" from documentation (which already lists the six eligible methods) rather than from whether the facade lets you call the method at all.

## What Changes

- `CachedCollection` and `CachedDatabase` (both `synchronous` and `asynchronous`) gain `__getattr__` delegation to the wrapped PyMongo `Collection`/`Database` for any attribute the class doesn't already define, so `collection.insert_one(...)`, `collection.create_index(...)`, `database.create_collection(...)`, etc. work directly on the facade without `.raw`.
- `.raw`'s documented role narrows, with no change to its behavior or signature: it remains exactly as it is today, but is documented only as the way to reach true PyMongo semantics for the six methods the facade already overrides (`find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, `distinct`) — for example a tailable/exhaust cursor or a `$changeStream` pipeline, cases the overrides themselves reject with `UnsupportedCacheRequestError`. It is no longer needed, and no longer documented, as the path for writes or any other non-overridden method, though existing code that still calls `.raw` for those keeps working unchanged.
- `CacheManager` itself is unchanged: no delegation to the wrapped `MongoClient` is added in this change; `manager.client` remains the way to reach it directly.
- README, `docs/api-reference.md`, and `docs/architecture.md` are rewritten wherever they currently instruct `.raw.insert_one(...)` (or any other non-overridden method) to call the facade method directly instead, and to describe `.raw`'s narrowed role.
- No OpenTelemetry or other per-call runtime instrumentation is added in this change; it stays a documentation-only answer to "is this method cached" (the six-method list), same as today.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `cached-read-api`: the requirement that "Unsupported operations SHALL remain available through the raw collection" changes to require that non-overridden PyMongo `Collection`/`Database` methods are directly callable on the facade (delegated to the wrapped object), while `.raw` is required only to bypass the six cache-aware overrides themselves.

## Impact

- Code: `src/client_query_cache/synchronous/collection.py`, `src/client_query_cache/synchronous/database.py`, `src/client_query_cache/asynchronous/collection.py`, `src/client_query_cache/asynchronous/database.py`.
- Tests: `tests/synchronous/test_collection.py`, `tests/synchronous/test_database.py`, `tests/asynchronous/test_collection.py`, `tests/asynchronous/test_database.py`, plus any test relying on `.raw` being the only reachable path for a write.
- Docs: `README.md`, `docs/api-reference.md`, `docs/architecture.md` (the "raw fallback" and "high-level design" sections).
- Public API: purely additive. Every PyMongo method becomes directly reachable on the facade without `.raw`; `.raw` itself keeps its existing signature and behavior, so no import or call site that works today stops working.
