# Design

## Context

See proposal.md for motivation and `specs/usage-examples/spec.md` for requirements.

Observed state of the integration targets (PyPI releases and the upstream repositories at the commits cited below):

- `requests-cache` 1.3.3 ships [`requests_cache/backends/mongodb.py`](https://github.com/requests-cache/requests-cache/blob/e95c652/requests_cache/backends/mongodb.py). `MongoCache(BaseCache)` builds two `MongoDict(BaseStorage)` objects, `responses` and `redirects`, from one `pymongo.MongoClient` (`connection=` reuses a caller's client). `MongoDict` does all I/O through `self.collection`:
  - reads: `__getitem__` → `find_one({'_id': key})`; `__iter__` → `find({}, {'_id': True})`; `__len__` → `estimated_document_count()`; `get_ttl` → `index_information()`;
  - writes/admin: `__setitem__` → `replace_one(..., upsert=True)`; `__delitem__` → `find_one_and_delete`; `bulk_delete` → `delete_many`; `clear` → `drop`; `set_ttl` → `create_index`/`drop_index` on `created_at` (TTL deletions arrive as change-stream deletes).
  - `requests_cache` ships `py.typed`, so its API can be type-checked.
- `aiohttp-client-cache` 0.14.3 implements `MongoDBBackend` in [`aiohttp_client_cache/backends/mongodb.py`](https://github.com/requests-cache/aiohttp-client-cache/blob/1bfe9cb/aiohttp_client_cache/backends/mongodb.py) on Motor's `AsyncIOMotorClient` and imports `motor` at module level. `client-query-cache` supports only `pymongo.AsyncMongoClient`. Upstream tracks the migration in [aiohttp-client-cache#415](https://github.com/requests-cache/aiohttp-client-cache/issues/415).
- On CPython 3.14.6, `requests-cache` 1.3.3, `aiohttp-client-cache` 0.14.3, `motor` 3.7.1, and `pymongo` 4.18.1 install and import together with the working-tree package.
- `CacheManager.cached(collection)` returns a `CachedCollection` exposing only six reads plus `.raw`. `find` returns a list. Cached values are BSON-decoded on every hit, so callers may mutate returned documents safely. Invalidation is asynchronous, and the public API has no per-write "wait until invalidated" primitive. `cache_manager.cache_core.snapshot()` exposes `hits`, `misses`, `bypasses`, and `entry_count`.
- A read against a collection that does not exist yet bypasses the cache. A cached `find_one` miss on an existing collection is cached negatively and invalidated by a later insert.
- `mypy.ini` checks `src`, `tests`, and `benchmarks`. Ruff and the other Prek hooks lint every tracked Python file. The `justfile` exports `UV_LOCKED=1`.

## Goals / Non-Goals

**Goals:**

- One example per target library, written the way a real adopter would write it, so interface friction shows up in the code rather than being hidden by test helpers.
- A single declaration of each example's third-party dependencies, reused by the run command, the pytest runner, and the type check.
- A written friction log that turns dogfooding into actionable follow-up changes.

**Non-Goals:**

- Changing `client_query_cache` source or its public API. Friction is recorded here and fixed in follow-up changes.
- Contributing to the upstream libraries. The examples subclass their public backend classes.
- Performance claims or benchmarks. The examples print cache statistics as evidence of behavior, not latency numbers. No library hot path changes, so the per-change benchmark rule does not apply; the commit body states that.
- Implementing the `aiohttp-client-cache` example before upstream #415 lands.

## Decisions

### D1. Dependencies via PEP 723 inline script metadata

Each example starts with a `# /// script` block declaring `requires-python = ">=3.14.6"`, `dependencies = ["client-query-cache", "<library>>=<tested version>"]`, and `[tool.uv.sources] client-query-cache = { path = "..", editable = true }`. `uv run examples/<example>.py` then builds an isolated, cached script environment that uses the working-tree package. This was verified with uv 0.12.9: a relative `path` source resolves against the script's directory, and `UV_LOCKED=1` does not reject an unlocked script. The type check reuses the same block via `uv run --with-requirements examples/<example>.py -- mypy examples/<example>.py`, which was verified to install the script's dependencies into the project environment for that one invocation.

Alternatives: `uv run --with requests-cache python examples/...` works too, but repeats the dependency list in the README, the justfile, the pytest parametrization, and the mypy step, where the lists can drift apart. The inline block is packaging metadata, not prose, so the no-comments rule does not apply to it. Adding an optional-dependency group to `pyproject.toml` is ruled out by the request.

### D2. requests-cache integration: subclass the upstream backend, route reads only

`examples/requests_cache_example.py` defines:

- `CachedMongoDict(MongoDict)`, constructed with a `CacheManager`. It keeps `self.collection` as the raw PyMongo collection for every write and admin call, and holds `self.cached_collection = cache_manager.cached(self.collection)`. It overrides only `__getitem__` (`cached_collection.find_one({'_id': key})`), `__iter__` (`cached_collection.find({}, {'_id': True})`), and `__len__` (`cached_collection.estimated_document_count()`), keeping upstream's result handling (`'data'` unwrapping, `KeyError`, `deserialize`).
- `CachedMongoCache(MongoCache)`, which takes a caller-owned `MongoClient` and `CacheManager` and installs `CachedMongoDict` instances as `responses` and `redirects`, preserving upstream's serializer arguments: `responses` keeps the default BSON-document serializer with `decode_content`, and `redirects` uses `serializer=None`.
- `main()`: opens `MongoClient(MONGODB_URI)` and `CacheManager(client)` with `with`, clears the example database, starts the local HTTP server (D3), builds `requests_cache.CachedSession(backend=CachedMongoCache(...))`, then runs the scenario in D4.

Swapping `self.collection` for the cached view is not possible, because the view deliberately has no write methods. Upstream calls writes on the same attribute. Needing to subclass and override three methods is itself a friction data point (D6).

Alternative: a from-scratch `BaseStorage`. Rejected because it would not show how an existing MongoDB-backed library adopts the cache.

### D3. Local in-process HTTP origin

`http.server.ThreadingHTTPServer` bound to `127.0.0.1:0`, served from a daemon thread, with a handler that increments a thread-safe origin-hit counter and returns a small JSON body. The server is shut down in `finally`/context-manager cleanup. This keeps the example offline and deterministic, and gives the origin counter that proves requests-cache served from storage.

### D4. Observable scenario and self-check

1. `GET /item` → origin hits 1. requests-cache writes the response through raw `replace_one`.
2. Repeat `GET /item` N times. Each requests-cache lookup calls `CachedMongoDict.__getitem__`. Assert origin hits stay 1 and `snapshot().hits` grew by at least N−1, since the first post-write lookup may be a miss that admits the entry.
3. Invalidate with a storage write through upstream's public API, `session.cache.delete(urls=[url])`, which issues raw `delete_many`. Poll `session.cache.contains(url=url)`, which reads through the cached `find_one`, until it returns `False`, bounded by a deadline (5 s). This is what a real adopter must do given asynchronous invalidation.
4. `GET /item` again → origin hits 2.

Each check that fails prints what was missing and exits via `SystemExit` with a non-zero status. On success, the example prints origin hits and the snapshot's `hits`, `misses`, and `bypasses`. Checks use plain `if` statements and not `assert`, so they survive `python -O`. The database name is a fixed constant (`client_query_cache_example_requests_cache`), dropped at start, so reruns stay deterministic. `MONGODB_URI` defaults to `mongodb://localhost:27017/?directConnection=true`, which matches `docker-compose.yaml`.

### D5. Verification wiring

- `tests/examples/test_examples.py` (`pytestmark = pytest.mark.integration`) parametrizes over example file names. Each case runs `uv run <example>` as a subprocess from the repository root with `MONGODB_URI` from the session `mongodb_uri` fixture, and asserts exit status 0, attaching stdout/stderr to the failure message. It uses a raised `@pytest.mark.timeout`, because the first run downloads packages. It is an integration test rather than e2e, because it runs the working tree and not a built wheel (see the `test-environment` tier definitions).
- `just examples` → `just pytest -- tests/examples`, one verification path with no second runner to keep in sync.
- `just lint` and the CI `package` job run a loop that type-checks each `examples/*.py` with `uv run --with-requirements "$f" -- mypy "$f"`. The main mypy `files` setting stays unchanged, so the main run never needs the example libraries.

Alternative: a standalone `just examples` that runs scripts against `docker-compose.yaml`. Rejected, because a second runner duplicates the example list and needs a manually started replica set, while the pytest fixture already provides a disposable one.

### D6. Friction log

While implementing each example, record every point where the public interface made the integration awkward, surprising, or impossible in a `## Friction log` section appended to this design. Each entry names the observed symptom, the example line that shows it, and a proposed follow-up change name. Candidates to evaluate, not yet confirmed: no drop-in collection-shaped object for libraries that call reads and writes on one attribute (D2); no public way to wait for a specific write's invalidation (D4); stats reachable only via `cache_manager.cache_core.snapshot()`. Follow-up changes are proposed separately and are not tracked as open tasks here.

### D7. aiohttp-client-cache example: blocked placeholder

This change carries the task in a blocked state. Once upstream #415 releases a PyMongo-async `MongoDBBackend`, the example mirrors D2–D4 on `AsyncMongoClient` and `client_query_cache.asynchronous.CacheManager` with `aiohttp` and an `aiohttp.web` local origin. No code, placeholder file, or skipped test is added for it until then.

## Risks / Trade-offs

- [The first `uv run` of an example downloads packages and can exceed pytest's 30 s default timeout] → Per-test raised timeout. uv's cache makes later runs fast. CI already has network access for `uv sync`.
- [Upstream releases can break the examples without any change in this repository] → Minimum-version pins in the script metadata. A break surfaces in CI as a named failing example, which is the dogfooding signal wanted.
- [Asynchronous invalidation can make the self-check flaky] → A bounded poll through the cached read path instead of a fixed sleep.
- [Examples use the cache's negative caching and "collection doesn't exist yet" bypass paths] → The self-check tolerates the first post-write miss (D4 step 2) instead of asserting exact counts.
- [The change cannot be archived while the aiohttp task is blocked] → This is intended by the user. The blocked task names its upstream unblock condition.
- [Ruff may flag `examples/*.py` (for example, implicit namespace package)] → Add a narrow `examples/*` per-file ignore in `ruff.toml` only for rules that fire, and do not add `__init__.py`.
