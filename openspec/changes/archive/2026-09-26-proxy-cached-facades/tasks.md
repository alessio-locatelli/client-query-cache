# Tasks

## 1. Synchronous collection proxy

- [x] 1.1 Add `__getattr__(self, name: str) -> Any` to `CachedCollection` in `src/client_query_cache/synchronous/collection.py`, delegating to `self._collection`, with a narrow `# noqa: ANN401` on that method; verify `just lint` (which runs `mypy --strict`) passes with no new suppressions elsewhere
- [x] 1.2 Add tests to `tests/synchronous/test_collection.py` covering: a non-overridden write (`insert_one`) and a non-overridden index/admin method (`create_index`) both callable directly on `CachedCollection` without `.raw`, and returning/behaving identically to calling the same method through `.raw`; verify with `just pytest tests/synchronous/test_collection.py`

## 2. Synchronous database proxy

- [x] 2.1 Add `__getattr__(self, name: str) -> Any` to `CachedDatabase` in `src/client_query_cache/synchronous/database.py`, delegating to `self._database`, with a narrow `# noqa: ANN401`; verify `just lint`
- [x] 2.2 Add tests to `tests/synchronous/test_database.py` covering a non-overridden database method (`create_collection` or `list_collection_names`) callable directly on `CachedDatabase` without `.raw`; verify with `just pytest tests/synchronous/test_database.py`

## 3. Asynchronous mirrors

- [x] 3.1 Apply the same `__getattr__` addition to `CachedCollection` in `src/client_query_cache/asynchronous/collection.py` and to `CachedDatabase` in `src/client_query_cache/asynchronous/database.py`, delegating to `self._collection`/`self._database` respectively; verify `just lint`
- [x] 3.2 Mirror the task 1.2 and 2.2 tests in `tests/asynchronous/test_collection.py` and `tests/asynchronous/test_database.py`, using `await` on the delegated coroutine methods; verify with `just pytest tests/asynchronous/`

## 4. Documentation

- [x] 4.1 Rewrite `README.md`'s usage examples that currently call `collection.raw.insert_one(...)`/`collection.raw.create_index(...)` to call the facade directly (`collection.insert_one(...)`, `collection.create_index(...)`), for both the synchronous and asyncio examples, and rewrite `docs/api-reference.md`'s "Every other PyMongo collection method ... is only available through `.raw`" line and its "Raw fallback" section to describe direct-call proxying plus `.raw`'s narrowed role (bypassing the six overrides for tailable/exhaust cursors and `$changeStream` pipelines); verify by running each rewritten snippet manually against a local MongoDB replica set (e.g. via `scripts/testcontainers-bridge.sh`) to confirm it executes as written
- [x] 4.2 Update `docs/architecture.md`'s high-level design diagram and "Why only reads are cached" section wherever they say "everything else via `.raw`" to describe the proxied direct-call surface, keeping `.raw`'s narrowed role explicit; verify by re-reading the section against the updated `docs/api-reference.md` for consistency

## 6. Review follow-up: keep delegated Collection/Database results cache-aware

- [x] 6.1 Codex review (round 1) found that `CachedDatabase`'s naive `__getattr__` returns a raw `Collection` for PyMongo's own attribute-style collection access (`database.users`), silently bypassing the cache where the pre-change code raised `AttributeError`. Fix `CachedCollection.__getattr__`/`CachedDatabase.__getattr__` (both sync and async) to detect a `Collection`/`Database`-valued attribute and wrap it in `CachedCollection`/`CachedDatabase`, mirroring `__getitem__`; verify with the added `test_*_attribute_access_returns_a_cached_*_facade` tests
- [x] 6.2 Codex review (round 2) found the same gap for delegated methods whose _return value_ is a `Collection`/`Database` (`Database.get_collection(...)`, `Collection.with_options(...)`, `Database.with_options(...)`), since those aren't reached through PyMongo's own `__getattr__` at all. Generalize the fix into a `_wrap_delegated` helper applied both to attribute values and, via a thin wrapper closure, to the return value of any delegated callable; verify with the added `test_*_get_collection_returns_a_cached_collection_facade` and `test_*_with_options_returns_a_cached_*_facade` tests
- [x] 6.3 Update the `cached-read-api` spec delta and `design.md` to document this as specified behavior (not an implementation detail): amend the MODIFIED requirement with the wrapping rule and two new scenarios, and replace design.md's now-inaccurate "identical bound method as `.raw`" decision with the actual `_wrap_delegated` rationale; verify with `openspec validate proxy-cached-facades --strict`
- [x] 6.4 Remove the now-false `test_*_proxies_non_overridden_methods_to_the_same_bound_method_as_raw` identity assertions (sync and async, collection and database) — delegated attributes are no longer the literal same bound-method object as `.raw`'s, only behaviorally equivalent — since the dedicated `insert_one`/`create_index`/`get_collection`/`with_options` tests already cover that equivalence by executing the calls; verify with `just pytest tests/synchronous/ tests/asynchronous/`

## 7. Code Quality

- [x] 7.1 Scan every test added or edited in this change (tasks 1.2, 2.2, 3.2, 6.1, 6.2, 6.4) and confirm the "Writing Tests" guidelines from `AGENTS.md` are applied, including `@pytest.mark.parametrize` for the repeated "call directly vs. call through `.raw`" assertions across methods where that fits without forcing an artificial abstraction
- [x] 7.2 Confirm no new prose/comments were added to `src/client_query_cache/synchronous/collection.py`, `synchronous/database.py`, `asynchronous/collection.py`, or `asynchronous/database.py` beyond the required `# noqa: ANN401` suppressions
