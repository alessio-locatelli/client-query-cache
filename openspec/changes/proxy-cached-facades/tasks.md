# Tasks

## 1. Synchronous collection proxy

- [ ] 1.1 Add `__getattr__(self, name: str) -> Any` to `CachedCollection` in `src/client_query_cache/synchronous/collection.py`, delegating to `self._collection`, with a narrow `# noqa: ANN401` on that method; verify `just lint` (which runs `mypy --strict`) passes with no new suppressions elsewhere
- [ ] 1.2 Add tests to `tests/synchronous/test_collection.py` covering: a non-overridden write (`insert_one`) and a non-overridden index/admin method (`create_index`) both callable directly on `CachedCollection` without `.raw`, and returning/behaving identically to calling the same method through `.raw`; verify with `just pytest tests/synchronous/test_collection.py`

## 2. Synchronous database proxy

- [ ] 2.1 Add `__getattr__(self, name: str) -> Any` to `CachedDatabase` in `src/client_query_cache/synchronous/database.py`, delegating to `self._database`, with a narrow `# noqa: ANN401`; verify `just lint`
- [ ] 2.2 Add tests to `tests/synchronous/test_database.py` covering a non-overridden database method (`create_collection` or `list_collection_names`) callable directly on `CachedDatabase` without `.raw`; verify with `just pytest tests/synchronous/test_database.py`

## 3. Asynchronous mirrors

- [ ] 3.1 Apply the same `__getattr__` addition to `CachedCollection` in `src/client_query_cache/asynchronous/collection.py` and to `CachedDatabase` in `src/client_query_cache/asynchronous/database.py`, delegating to `self._collection`/`self._database` respectively; verify `just lint`
- [ ] 3.2 Mirror the task 1.2 and 2.2 tests in `tests/asynchronous/test_collection.py` and `tests/asynchronous/test_database.py`, using `await` on the delegated coroutine methods; verify with `just pytest tests/asynchronous/`

## 4. Documentation

- [ ] 4.1 Rewrite `README.md`'s usage examples that currently call `collection.raw.insert_one(...)`/`collection.raw.create_index(...)` to call the facade directly (`collection.insert_one(...)`, `collection.create_index(...)`), for both the synchronous and asyncio examples, and rewrite `docs/api-reference.md`'s "Every other PyMongo collection method ... is only available through `.raw`" line and its "Raw fallback" section to describe direct-call proxying plus `.raw`'s narrowed role (bypassing the six overrides for tailable/exhaust cursors and `$changeStream` pipelines); verify by running each rewritten snippet manually against a local MongoDB replica set (e.g. via `scripts/testcontainers-bridge.sh`) to confirm it executes as written
- [ ] 4.2 Update `docs/architecture.md`'s high-level design diagram and "Why only reads are cached" section wherever they say "everything else via `.raw`" to describe the proxied direct-call surface, keeping `.raw`'s narrowed role explicit; verify by re-reading the section against the updated `docs/api-reference.md` for consistency

## 5. Code Quality

- [ ] 5.1 Scan every test added or edited in this change (tasks 1.2, 2.2, 3.2) and confirm the "Writing Tests" guidelines from `AGENTS.md` are applied, including `@pytest.mark.parametrize` for the repeated "call directly vs. call through `.raw`" assertions across methods where that fits without forcing an artificial abstraction
- [ ] 5.2 Confirm no new prose/comments were added to `src/client_query_cache/synchronous/collection.py`, `synchronous/database.py`, `asynchronous/collection.py`, or `asynchronous/database.py` beyond the required `# noqa: ANN401` suppressions
