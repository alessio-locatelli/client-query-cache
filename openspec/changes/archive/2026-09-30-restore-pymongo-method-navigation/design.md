# Design

## Context

See [proposal.md](proposal.md) for the user-facing problem. `CachedCollection` and `CachedDatabase` are composed views that currently forward every unknown attribute through `__getattr__ -> Any`; `docs/api-reference.md` already records the resulting loss of argument and return-type checking. The archived `proxy-cached-facades` design deliberately left IDE autocomplete out of scope. The six cached collection reads are explicitly declared, and `.raw` is typed as the underlying PyMongo object.

The current read API is intentionally different from PyMongo's: synchronous `CachedCollection.find()` and `aggregate()` return lists, whereas PyMongo returns cursors; asynchronous `CachedCollection.find()` is awaited and returns a list, whereas PyMongo's `AsyncCollection.find()` immediately returns an async cursor. The cached view also rejects some unbounded cursor requests. Those differences rule out claiming that the cached view is a subtype of PyMongo's collection. The caller still owns the `MongoClient`/`AsyncMongoClient`; the manager owns the cache and change-stream coordinator.

There are no real users of this library yet. Public documentation therefore needs to explain only the resulting API; the Unreleased changelog entry is enough to record the interface change. The delta spec's `Migration` fields are internal OpenSpec metadata, not public documentation work.

## Goals / Non-Goals

**Goals:** Restore PyMongo method discovery, source navigation, and argument/return typing for ordinary operations; retain an explicit typed path for all six cached reads; preserve client ownership and cache behavior.

**Non-Goals:** Make cached reads drop-in PyMongo cursor operations, replace the caller's client, or add a new single-context-manager constructor. A client-owning convenience wrapper could be combined with the explicit read view but is a separate lifecycle decision from restoring method navigation.

## Decisions

### Use a real PyMongo object for ordinary operations

The documented pattern becomes:

```python
with MongoClient(uri) as client, CacheManager(client) as cache_manager:
    collection = client["my_database"]["my_collection"]
    cached_collection = cache_manager.cached(collection)
    collection.insert_one({"_id": "example", "value": 42})
    document = cached_collection.find_one({"_id": "example"})
```

Keep the public class name `CacheManager` because it names the existing cache and change-stream owner; use `cache_manager` for that instance in all new examples. Renaming the class would add a second public API change without helping method navigation.

`CacheManager.cached(collection)` accepts a synchronous `Collection[DocumentType]` or, in the asyncio package, an `AsyncCollection[DocumentType]`. It checks that `collection.database.client is cache_manager.client` before constructing the same lightweight `CachedDatabase`/`CachedCollection` view used by `cache_manager[database][collection]`. The returned view's `.raw` is the exact supplied collection, so `get_collection(...)` and `with_options(...)` keep their codec, read/write concern, and read preference choices. An unrelated client's collection raises `ValueError`; the cache manager must never watch one client while executing cached reads through another. The explicit accessor performs only local object work and no MongoDB request. Existing cache manager indexing remains available for the six cached reads.

Each call creates a new lightweight view. Views from the same cache manager share its `CacheCore`, metadata caches, and `ChangeStreamCoordinator`; the coordinator keeps one supervisor per active database, keyed by database name. Repeated `cached(collection)` calls are therefore safe and share cached entries when the namespace and read shape match, but object identity is not part of the API. Reuse a local view when convenient; do not add a view singleton registry or a second cache instance.

Remove general `__getattr__` delegation and its callable-result wrapping from both cached view types. Keep attribute-style access to _subcollections_ by returning a typed cached view for a name absent from the PyMongo object's declared attributes; a request for an actual PyMongo method/property name that the view does not declare raises `AttributeError`, directing the caller to the original object or `.raw`. `CachedDatabase` already has `__getitem__`; add a typed `CachedCollection.__getitem__` that wraps `self.raw[name]`, making bracket access the unambiguous subcollection-name path even when a name collides with a method. Static analysis then sees `cached_collection.insert_one(...)` as an invalid call rather than treating it as `Any`; `collection.insert_one(...)` resolves to PyMongo's method. The view retains the six explicit cache-aware read methods and `.raw` for PyMongo semantics under those same names.

### Do not make the cache view a PyMongo subclass

Subclassing `Collection`/`AsyncCollection` would make inherited writes navigable, but the cached `find`/`aggregate` overrides cannot satisfy the base return contracts. It would also expose inherited methods that can construct raw collections (`with_options`, `get_collection`, subcollection access) unless every escape path were audited. A `CachedMongoClient` subclass alone would not repair the collection's `Any` delegation and would reintroduce client ownership and factory behavior questions from `prototype-recovery`.

A composed `CachedMongoClient` could instead construct both a PyMongo client and a `CacheManager`, close both in one context, and expose a real PyMongo collection plus `cached(collection)`. That would preserve method navigation while reducing the context-manager count. It would still require two distinct collection handles because their `find` return types differ, and it would need a clear rule for who closes a caller-supplied client versus one it constructs, plus sync/async constructor and option-forwarding behavior. This change keeps the existing caller-owned client boundary and fixes the reported navigation failure without adding that second ownership mode. The combined wrapper remains a viable separate API decision, not an incompatibility of the chosen read-view design.

### Do not mirror PyMongo's whole surface in wrappers or stubs

Handwritten or generated passthrough methods could expose signatures for today's driver, but they duplicate a large, evolving API across synchronous and asyncio variants. A stub-only solution makes source navigation land on our stub or wrapper instead of the PyMongo implementation and can disagree with runtime delegation. These costs are unnecessary when callers already own a fully typed PyMongo object. A static type trick that declares the facade as a PyMongo subtype while retaining composition would also misrepresent the cursor return contracts.

### Accept an explicit cached-read boundary

The two handles name different behavior: `collection.find(...)` has native PyMongo cursor semantics, while `cached_collection.find(...)` has the library's fully materialized cache semantics. This avoids a misleading single object whose method names appear PyMongo-compatible but return different types. It also lets callers use a configured raw collection directly for transactions, writes, administration, and unsupported reads. Public examples show only these current semantics; the Unreleased changelog records the interface change once.

### Exercise the API against a real consumer shape

The local `requests-cache` checkout's [`MongoDict`](https://github.com/requests-cache/requests-cache/blob/e95c652c36943b76317a20c9b2a54f2a0370e813/requests_cache/backends/mongodb.py) holds one PyMongo `collection`. Its `__getitem__`, `__len__`, and `__iter__` read through `find_one`, `estimated_document_count`, and `find`; its mutation, index, and `clear()` paths use PyMongo's `replace_one`, `find_one_and_delete`, `delete_many`, `index_information`, `create_index`, `drop_index`, and `drop`. A consumer adapting that class could keep `self.collection` as the PyMongo object and hold `self.cached_collection = cache_manager.cached(self.collection)` for eligible reads. This demonstrates why both handles need clear names and why `cached(...)` must be safe to call wherever a component already holds the raw collection.

This is an internal usability exercise, not a public integration example: the checkout's `MongoDict.close()` closes its `connection` even when a caller supplied it, so a drop-in example sharing that client with this cache would misstate resource ownership. Do not change the `requests-cache` checkout in this change. If a public integration example is ever added, its client lifetime and MongoDB topology must be accurate for the actual consumer.

## Risks / Trade-offs

- [Repository call sites that use delegated methods on cached views will fail after the change] → Convert them to the original PyMongo object or `.raw`; cover representative synchronous and asyncio call sites and preserve cache manager indexing for cache-aware reads.
- [A caller may accidentally use `collection.find_one(...)` and bypass caching] → Keep the names `collection` and `cached_collection` distinct in examples and describe the operation boundary in the API reference. This is an observable usage choice, not a hidden fallback.
- [A typed `__getattr__` for subcollections may still suggest a collection for an unknown misspelled attribute] → Match PyMongo's existing dot-access convention; ordinary method names already declared by PyMongo must raise on the cached view. Recommend bracket access where collection names could collide with methods.
- [The new accessor could pair a collection with the wrong stream owner] → Check exact client identity before creating the view; preserve the supplied raw handle and all its options.
- [Removing proxy wrapping changes `with_options`/`get_collection` call sites] → Use those methods on the raw PyMongo object and pass the result through `cache_manager.cached(...)`; verify this retains options and cache eligibility in both execution models.
- [Performance could regress if view creation or cached reads gain work] → Keep the ownership check at view construction and out of the read path. Compare cached-read hit/miss and view-construction measurements with the existing baseline during implementation, and record representative measurements in the commit body.

## Migration Plan

Release the explicit accessor and removal of generic delegation together. Update the README and API reference to describe current behavior only, and add one Unreleased changelog entry. Convert repository writes/admin calls on `CachedCollection`/`CachedDatabase` to the original PyMongo handle or `.raw`; convert option-returning calls to PyMongo followed by `cache_manager.cached(...)`. Existing `cache_manager["db"]["collection"]` cached-read calls and `.raw` fallback remain valid. Rollback is a normal code/package version revert; the cache stores no persistent data.
