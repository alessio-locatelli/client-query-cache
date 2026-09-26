# Design

## Context

`CachedCollection` and `CachedDatabase` (`src/client_query_cache/synchronous/{collection,database}.py` and their `asynchronous/` mirrors) are `__slots__`-based classes with no `__getattr__`. Each defines a small, fixed surface — the six cache-aware read methods plus `raw`/`name`/`database`/`manager` (or `raw`/`name`/`manager`/`__getitem__` for `CachedDatabase`) — and nothing else, so any other PyMongo `Collection`/`Database` method is an `AttributeError` unless reached through `.raw`. See proposal.md - Why for the swappability problem this causes.

The project runs `mypy --strict` with `disallow_any_generics=True` (`mypy.ini`) and Ruff `select = ["ALL"]` with no blanket `ANN401` (`any-type`) ignore (`ruff.toml`), so an `Any`-returning method needs a deliberate, narrow suppression, not a config-wide one.

## Goals / Non-Goals

**Goals:**

- Any `Collection`/`Database` attribute the facade doesn't itself define resolves to the wrapped PyMongo object's attribute, bound the same way it would be on that object directly.
- The six existing overrides, and `raw`/`name`/`database`/`manager`/`__getitem__`, keep their exact current behavior — the proxy only fills in what's currently missing, it doesn't change anything that already resolves.
- Both `synchronous` and `asynchronous` facades get the same treatment, kept symmetric the way the rest of the codebase already mirrors sync/async.

**Non-Goals:**

- `CacheManager` gaining delegation to the wrapped `MongoClient` — out of scope per the proposal; `manager.client` already reaches it.
- Any per-call runtime signal (OpenTelemetry or otherwise) for whether a given call was cache-aware — out of scope per the proposal; the six-method list in the docs stays the static answer.
- Introspection helpers (`__dir__`, `__dict__` exposure, IDE autocomplete for proxied members) — discovering the full proxied surface is answered by PyMongo's own documentation for `Collection`/`Database`, consistent with the proposal's premise that eligibility is a documentation question, not a facade-shape question.
- Proxying attribute _assignment_ (`collection.some_attr = value`) — PyMongo's `Collection`/`Database` have no supported public attribute meant to be set post-construction, so `__setattr__` delegation is not needed.

## Decisions

### Use `__getattr__`, not enumerated method copying

Considered generating explicit passthrough methods for every `pymongo.Collection`/`Database` method (e.g. via a code-gen step or a loop over `dir()` at class-definition time). Rejected: it would need re-running whenever a pymongo upgrade adds or removes a method, and the whole point of this change is that the facade shouldn't need to track PyMongo's surface method-by-method. `__getattr__` is looked up only after normal attribute resolution fails (the six overrides and the existing properties all resolve first, unaffected), and it works fine alongside `__slots__` — `__getattr__` doesn't require `__dict__`, only the fallback hook.

```python
def __getattr__(self, name: str) -> Any:  # noqa: ANN401
    return getattr(self._collection, name)
```

The `ANN401` suppression is narrow (this one method) rather than a project-wide `ruff.toml` ignore, matching the existing pattern of per-line `# noqa` use elsewhere in the codebase (e.g. `tests/synchronous/test_streams.py`) rather than disabling the rule.

### Delegate to the same object `.raw` already exposes, except when the result is itself a Collection or Database

`__getattr__` starts from `getattr(self._collection, name)` (and `getattr(self._database, name)` for `CachedDatabase`) — the identical object `.raw` already returns. For most names this is the whole story: `collection.insert_one(...)` and `collection.raw.insert_one(...)` reach the same underlying PyMongo call with the same arguments, same codec options, same read/write concern.

It is not the whole story for two categories of PyMongo attribute, both already covered by codex review during this change's own implementation:

- **Attribute-style collection access.** `pymongo.Database.__getattr__` and `pymongo.Collection.__getattr__` both exist independently of this change, and both return a raw sub-`Collection` for any attribute name they don't otherwise define (`database.users` is equivalent to `database["users"]`; `collection.chunks` names the sub-collection `"<name>.chunks"`). Before this change, `CachedDatabase`/`CachedCollection` had no `__getattr__` at all, so this path raised `AttributeError` — safe, if inconvenient. A naive `return getattr(self._database, name)` makes it succeed while silently handing back an uncached raw `Collection`, defeating the cache for anyone using PyMongo's own dot-access idiom, worse than the `AttributeError` it replaces.
- **Methods that return a new Collection or Database.** `Database.get_collection(...)` and `Collection.with_options(...)`/`Database.with_options(...)` are ordinary, already-existing PyMongo methods (not reached through PyMongo's own `__getattr__`) whose entire purpose is to hand back another `Collection`/`Database`. Delegating the bound method unchanged means calling it returns a raw object the same way.

Both categories share one shape: something this facade proxies — either an attribute value or the return value of a proxied call — is itself a `Collection` or `Database` that ought to be wrapped the same way `__getitem__` already wraps one. `_wrap_delegated` centralizes that: given any value obtained through delegation, if it's a `Collection` it becomes a `CachedCollection`; if it's a `Database` it becomes a `CachedDatabase` (via the same manager); otherwise, if it's callable, it's replaced with a thin wrapper that calls through and applies `_wrap_delegated` again to _that_ result, so a delegated method returning a Collection/Database is caught without this facade needing to know that method's name in advance — only PyMongo's own `Collection.get_collection`/`with_options` methods are exempt from this file needing to enumerate them, because their result type is detected at call time, not declared here. Non-collection, non-database, non-callable values (documents, counts, cursors, `InsertOneResult`, and so on) pass through untouched.

This means `collection.insert_one` is no longer literally the same bound-method object as `collection.raw.insert_one` — `__getattr__` now always returns a wrapper closure for a callable attribute, in case calling it later turns out to return a Collection/Database. Calling either produces the same PyMongo call with the same arguments and the same observable result; only object identity of the _unwritten-to_ attribute differs, which nothing in this library's public contract promises anyway.

### Leave the six overrides and existing properties exactly as they are

`__getattr__` is never consulted for `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, `distinct`, `raw`, `name`, `database`, `manager`, or `CachedDatabase.__getitem__` — Python resolves those through the class before ever falling back to `__getattr__`. This is why `CachedCollection.database` can keep returning the owning `CachedDatabase` (shadowing what `pymongo.Collection.database` would otherwise return) without the proxy fighting it: the override wins by normal attribute-lookup order, not by any special-casing in `__getattr__` itself.

### Mypy return type

`__getattr__`'s return type is necessarily `Any` — the whole point is that the facade cannot know in advance which PyMongo attribute a caller will reach for. This means a call like `collection.insert_one(document)` type-checks but without argument or return-type validation against `Collection.insert_one`'s real signature, unlike the six explicitly-typed overrides. This is an accepted, inherent trade-off of a generic proxy (see Risks below), not something to design around with per-method type stubs — enumerating every method's signature would reintroduce the drift problem `__getattr__` avoids.

## Risks / Trade-offs

- **A delegated call now goes through one extra Python-level function call (the `_delegate` closure) so its result can be checked against `Collection`/`Database`** → Accepted: this only affects non-cached delegated calls (writes, admin methods), never the six cache-aware overrides, which don't go through `__getattr__` at all. The added overhead is a single `isinstance` check plus one extra frame — negligible next to the network round-trip any real PyMongo call already makes.
- **Loss of static type-checking for proxied calls** → Accepted: the six cache-aware methods keep their full type signatures (unchanged by this design); only the passthrough surface loses argument/return typing, matching what a caller already accepts today by reaching for `.raw` (which is also typed as the concrete PyMongo `Collection`/`Database`, so this is actually a slight typing regression versus explicit `.raw.insert_one(...)`, which mypy fully checks). Document this trade-off in `docs/api-reference.md` so callers who want full static checking for a write know to still use `.raw` for it.
- **A typo in a method name that isn't a real PyMongo attribute now raises `AttributeError` from deep inside the delegation instead of from the facade itself** → Low severity: the error message and type are the same (`AttributeError: 'Collection' object has no attribute '...'`) whether raised directly or through one level of `getattr`; no behavior to mitigate.
- **Existing tests and docs assume `.raw` is the only reachable path for a write** → Addressed directly by this change's task list: every `.raw.insert_one`-style example in README/docs that isn't demonstrating the narrowed `.raw` role is rewritten to call the facade method directly, and tests gain coverage for the new direct-call path without removing existing `.raw`-based assertions (both remain valid, since `.raw` is unchanged).

## Migration Plan

Purely additive at the code level — no signature changes, no deprecation warnings, no data migration. Ship as a normal release: implement the `__getattr__` addition on both facades' collection and database classes, update docs, land in one change. No rollback concern beyond a normal revert, since nothing existing is removed or altered.
