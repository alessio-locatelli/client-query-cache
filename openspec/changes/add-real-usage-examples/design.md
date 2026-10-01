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

Each example starts with a `# /// script` block declaring `requires-python = ">=3.14.6"`, `dependencies = ["client-query-cache", "<library>>=<tested version>"]`, and `[tool.uv.sources] client-query-cache = { path = "..", editable = true }`. `uv run examples/<example>.py` then builds an isolated, cached script environment that uses the working-tree package. This was verified with uv 0.12.9: a relative `path` source resolves against the script's directory, and `UV_LOCKED=1` does not reject an unlocked script. The type check reuses the same block: `uv sync --script examples/<example>.py` builds the script environment, and the project's mypy checks the example against it with `--python-executable`, using the interpreter path from the sync's `--output-format json` report (`sync.environment.python.path`). `uv python find --script` is rejected for this: when `UV_PYTHON` is set, as `astral-sh/setup-uv` does in CI (`UV_PYTHON=3.14`), it can return an interpreter other than the synced script environment, such as the project `.venv` or a bare, freshly downloaded CPython. Verified with uv 0.12.9 and in CI with uv 0.12.19. `uv sync --script` rejects `UV_LOCKED=1` without a script lockfile, so the recipe runs it with `UV_LOCKED` unset, as `verify-release` already does. `uv run --with-requirements examples/<example>.py -- mypy ...` is rejected: verified with uv 0.12.9, the overlay ignores the script's `[tool.uv.sources]` and installs the published `client-query-cache` from PyPI, so it would type-check the example against the last release instead of the working tree.

Alternatives: `uv run --with requests-cache python examples/...` works too, but repeats the dependency list in the README, the justfile, the pytest parametrization, and the mypy step, where the lists can drift apart. The inline block is packaging metadata, not prose, so the no-comments rule does not apply to it. Adding an optional-dependency group to `pyproject.toml` is ruled out by the request.

### D2. requests-cache integration: subclass the upstream backend, route reads only

`examples/requests_cache_example.py` defines:

- `CachedMongoDict(MongoDict)`, constructed with a `CacheManager`. It keeps `self.collection` as the raw PyMongo collection for every write and admin call, and holds `self.cached_collection = cache_manager.cached(self.collection)`. It overrides only `__getitem__` (`cached_collection.find_one({'_id': key})`), `__iter__` (`cached_collection.find({}, {'_id': True})`), and `__len__` (`cached_collection.estimated_document_count()`), keeping upstream's result handling (`'data'` unwrapping, `KeyError`, `deserialize`).
- `CachedMongoCache(MongoCache)`, which takes a `CacheManager`, reuses its caller-owned `MongoClient` (`cache_manager.client`, so `cached()` never sees a collection from another client), and installs `CachedMongoDict` instances as `responses` and `redirects`, preserving upstream's serializer arguments: `responses` keeps the default BSON-document serializer with `decode_content`, and `redirects` uses `serializer=None`.
- `main()`: opens `MongoClient(MONGODB_URI)` and `CacheManager(client)` with `with`, clears the example database, starts the local HTTP server (D3), builds `requests_cache.CachedSession(backend=CachedMongoCache(...), autoclose=False)` so that closing the session leaves the caller-owned client open, then runs the scenario in D4.

Swapping `self.collection` for the cached view is not possible, because the view deliberately has no write methods. Upstream calls writes on the same attribute. Needing to subclass and override three methods is itself a friction data point (D6).

Alternative: a from-scratch `BaseStorage`. Rejected because it would not show how an existing MongoDB-backed library adopts the cache.

### D3. Local in-process HTTP origin

`http.server.ThreadingHTTPServer` bound to `127.0.0.1:0`, served from a daemon thread, with a handler that increments a thread-safe origin-hit counter and returns a small JSON body. The server is shut down in `finally`/context-manager cleanup. This keeps the example offline and deterministic, and gives the origin counter that proves requests-cache served from storage.

### D4. Observable scenario and self-check

1. `GET /item` → origin hits 1. requests-cache writes the response through raw `replace_one`.
2. Repeat `GET /item` N times. Each requests-cache lookup calls `CachedMongoDict.__getitem__`. Assert origin hits stay 1 and `snapshot().hits` grew by at least N−1, since the first post-write lookup may be a miss that admits the entry.
3. Invalidate with a storage write through upstream's public API, `session.cache.delete(urls=[url])`, which deletes a single key through raw `find_one_and_delete` (upstream switches to `delete_many` only for several keys). Poll `session.cache.contains(url=url)`, which reads through the cached `find_one`, until it returns `False`, bounded by a deadline (5 s). This is what a real adopter must do given asynchronous invalidation.
4. `GET /item` again → origin hits 2.

Each check that fails prints what was missing and exits via `SystemExit` with a non-zero status. On success, the example prints origin hits and the snapshot's `hits`, `misses`, and `bypasses`. Checks use plain `if` statements and not `assert`, so they survive `python -O`. The database name is a fixed constant (`client_query_cache_example_requests_cache`), dropped at start, so reruns stay deterministic. `MONGODB_URI` defaults to `mongodb://localhost:27017/?directConnection=true`, which matches `docker-compose.yaml`.

### D5. Verification wiring

- `tests/examples/test_examples.py` (`pytestmark = pytest.mark.integration`) parametrizes over example file names. Each case runs `uv run <example>` as a subprocess from the repository root with `MONGODB_URI` from the session `mongodb_uri` fixture, and asserts exit status 0, attaching stdout/stderr to the failure message. It uses a raised `@pytest.mark.timeout`, because the first run downloads packages. It is an integration test rather than e2e, because it runs the working tree and not a built wheel (see the `test-environment` tier definitions).
- `just examples` → `just pytest -- tests/examples`, one verification path with no second runner to keep in sync.
- `just lint` and the CI `package` job run a loop that syncs each `examples/*.py` script environment and type-checks the example against it (D1). The main mypy `files` setting stays unchanged, so the main run never needs the example libraries.

Alternative: a standalone `just examples` that runs scripts against `docker-compose.yaml`. Rejected, because a second runner duplicates the example list and needs a manually started replica set, while the pytest fixture already provides a disposable one.

### D6. Friction log

While implementing each example, record every point where the public interface made the integration awkward, surprising, or impossible in a `## Friction log` section appended to this design. Each entry names the observed symptom, the example code that shows it (by symbol, since line numbers drift), the constraints a follow-up proposal must respect, and a proposed follow-up change name. Candidates to evaluate, not yet confirmed: no drop-in collection-shaped object for libraries that call reads and writes on one attribute (D2); no public way to wait for a specific write's invalidation (D4); stats reachable only via `cache_manager.cache_core.snapshot()`. Follow-up changes are proposed separately and are not tracked as open tasks here.

### D7. aiohttp-client-cache example: blocked placeholder

This change carries the task in a blocked state. Once upstream #415 releases a PyMongo-async `MongoDBBackend`, the example mirrors D2–D4 on `AsyncMongoClient` and `client_query_cache.asynchronous.CacheManager` with `aiohttp` and an `aiohttp.web` local origin. No code, placeholder file, or skipped test is added for it until then.

### D8. Additional targets and feasibility gates

Pursue Celery, py-abac, and Eve in that order, then investigate Hyperopt. These are planned integrations, not verified runnable examples. Before implementation, select a published release, verify its source and dependencies against the project's supported Python/PyMongo environment, and record the exact release and source revision. The upstream links below establish candidate read paths only; they do not establish released-version compatibility or popularity. Record adapter constraints and concrete blockers here, without adding placeholder scripts or skipped tests. An infeasible required target needs an explicit planning revision before its implementation obligation can be removed.

- **Celery:** The [MongoDB result backend](https://github.com/celery/celery/blob/main/celery/backends/mongodb.py) reads task and group records with `find_one({'_id': ...})` and writes through raw collection methods. Subclass the backend to route selected reads through a cached view while preserving upstream decoding, metadata handling, raw writes/admin calls, and caller-owned client lifecycle. Confirm a supported way to reuse the manager's client before settling the adapter. Demonstrate repeated polling of an unfinished task, then a state/result write and bounded observation of its invalidation, without requiring an external broker or worker. Do not use repeated reads of a completed `AsyncResult` as cache evidence: [AsyncResult](https://github.com/celery/celery/blob/main/celery/result.py) retains ready-state metadata, and the [backend](https://github.com/celery/celery/blob/main/celery/backends/base.py) can also cache successful results. Ensure the chosen public read path reaches the MongoDB adapter on repeated calls and attribute hits to `client-query-cache` statistics.
- **py-abac:** [MongoStorage](https://github.com/ketgo/py-abac/blob/master/py_abac/storage/mongo/storage.py) uses scalar `_id` `find_one` in `get`, `find` in `get_all`, and `aggregate` in `get_for_target`. A storage subclass can retain raw `add`/`update`/`delete` and redirect these reads, preserving validation and policy conversion. Verify the released [target pipeline](https://github.com/ketgo/py-abac/blob/master/py_abac/storage/mongo/model.py) against cache eligibility rules rather than assuming all aggregations cache. Exercise policy retrieval and authorization evaluation, including a policy update whose changed decision is eventually observed; prove cache hits for each supported read shape used by the example.
- **Eve:** The [Mongo data layer](https://github.com/pyeve/eve/blob/master/eve/io/mongo/mongo.py) performs `find`, `count_documents`, and `find_one` reads. Prototype a data-layer subclass and inspect its consumers before choosing overrides: cached `find` returns a list, so native cursor assumptions, pagination, sorting, projection, authorization filters, and response metadata must remain correct. Use an in-process application client for repeated GETs and a mutation, with bounded invalidation observation and cache statistics. Keep writes on the upstream raw path. Record incompatibilities rather than replacing the whole collection with the read-only facade or promising a cursor-compatible adapter.
- **Hyperopt (investigation only):** The inspected [MongoTrials implementation](https://github.com/hyperopt/hyperopt/blob/master/hyperopt/mongoexp.py) contains legacy calls such as `find_and_modify`, `collection.update`, and cursor `count`. Verify a published version's compatibility and its repeated-read opportunities before proposing implementation. Assess both cursor requirements and invalidation frequency during trial updates. Do not modify upstream or expand this change into an upstream compatibility repair. Record a go/no-go decision with version/source evidence; adding a runnable example requires a subsequent approved revision of this plan.

Each delivered example follows D1, D5, and D6: inline dependencies, existing subprocess/type-check verification, public cache statistics, bounded self-checks, and a friction log. Add only delivered examples to `examples/README.md`; do not publish this candidate backlog as runnable usage guidance. No new requirement is needed in the usage-examples delta spec, whose library-independent requirements already cover these targets.

## Risks / Trade-offs

- [The first `uv run` of an example downloads packages and can exceed pytest's 30 s default timeout] → Per-test raised timeout. uv's cache makes later runs fast. CI already has network access for `uv sync`.
- [Upstream releases can break the examples without any change in this repository] → Minimum-version pins in the script metadata. A break surfaces in CI as a named failing example, which is the dogfooding signal wanted.
- [Asynchronous invalidation can make the self-check flaky] → A bounded poll through the cached read path instead of a fixed sleep.
- [Examples use the cache's negative caching and "collection doesn't exist yet" bypass paths] → The self-check tolerates the first post-write miss (D4 step 2) instead of asserting exact counts.
- [The change cannot be archived while the aiohttp task is blocked] → This is intended by the user. The blocked task names its upstream unblock condition.
- [Ruff may flag `examples/*.py` (for example, implicit namespace package)] → Add a narrow `examples/*` per-file ignore in `ruff.toml` only for rules that fire, and do not add `__init__.py`.

## Friction log

Observed while writing `examples/requests_cache_example.py` against requests-cache 1.3.3. Code is cited by symbol rather than line number. Paths are relative to the repository root.

Confirmed:

- **No drop-in collection-shaped object** (D6 candidate, confirmed).
  - Symptom: requests-cache's `MongoDict` calls reads and writes on the same `self.collection` attribute, and `CachedCollection` has no write methods. The example therefore keeps `self.collection` as the raw PyMongo collection, adds a second attribute, `CachedMongoDict.cached_collection`, and overrides `CachedMongoDict.__getitem__`, `__iter__`, and `__len__`. The `__getitem__` override copies upstream's result handling (`'data'` unwrapping, `KeyError`, `deserialize`) only to change which object it calls, so it can drift from upstream.
  - Constraint: views without write methods were a deliberate decision. `openspec/changes/archive/2026-09-30-restore-pymongo-method-navigation/design.md` removed attribute forwarding from the views and lists "make cached reads drop-in PyMongo cursor operations" as a non-goal. `openspec/changes/archive/2026-09-26-proxy-cached-facades/design.md` holds the earlier forwarding design. A proposal must either work within that decision or explicitly revisit it. Note that `find` returns a list, not a cursor.
  - Proposed follow-up: `evaluate-read-through-collection-adapter`, which weighs an opt-in object that serves the six cached reads from the cache and forwards writes to PyMongo.
- **No public way to wait for a write's invalidation** (D6 candidate, confirmed).
  - Symptom: after `session.cache.delete(...)` in `run_scenario`, the example can only poll `session.cache.contains(...)` against a fixed deadline (`INVALIDATION_TIMEOUT_SECONDS`). The loop cannot tell a slow change stream from a lost event. A clean run observes invalidation after about 6 ms on a local replica set.
  - Constraint: invalidation arrives asynchronously from a per-database change stream (`src/client_query_cache/synchronous/streams.py`). The public API has no mapping from a completed write to a change-stream position (for example, the write's operation time compared with the stream's resume point). A proposal must define that mapping for both the synchronous and asyncio packages.
  - Proposed follow-up: `add-invalidation-wait-primitive`.
- **Statistics only through `cache_core`** (D6 candidate, confirmed).
  - Symptom: to report hits, `main` and `run_scenario` go through `cache_manager.cache_core.snapshot()` and import `CacheCore` just for a type annotation. The name "core" reads as an internal layer, not a user-facing statistics entry point.
  - Existing surface: `CacheManager.cache_core` is a public, documented property (`docs/api-reference.md`, `docs/architecture.md` "Observability"). `snapshot()` returns `CacheSnapshot` (`src/client_query_cache/_core/snapshots.py`), whose fields include `hits`, `misses`, `evictions`, `bypasses`, `oversized_bypasses`, and `entry_count`. `client_query_cache.otel.register_cache_metrics` also takes `cache_core`. A proposal changes only where users reach statistics, not what is counted.
  - Proposed follow-up: `add-manager-statistics-accessor`.
- **Bypasses carry no reason**.
  - Symptom: a clean run reports `bypasses: 5`. Instrumenting `CachedMongoDict.__getitem__` and `__iter__` attributed them as follows: one `responses` lookup during the first request, before requests-cache has created the `responses` collection, and four `redirects` reads (three lookups and one iteration), because the scenario never creates the `redirects` collection. All five are expected, because reads against a collection that does not exist yet bypass the cache. `CacheSnapshot` gives an adopter no way to tell these apart from a misconfiguration such as a non-primary read preference or a session argument.
  - Constraint: bypasses are counted by one untyped call. `CachedCollection._record_bypass` in both `src/client_query_cache/synchronous/collection.py` and `src/client_query_cache/asynchronous/collection.py` is called from every bypass branch in the view, and `CacheCore` records further bypasses internally (`src/client_query_cache/_core/manager.py`, calls to `self._statistics.record_bypass()`). A reason has to be passed at each of these call sites. The OpenTelemetry bridge in `src/client_query_cache/otel.py` exports the counter and would need a matching attribute.
  - Proposed follow-up: `add-bypass-reason-statistics`.

Dropped, because the cause is upstream and not in this package:

- requests-cache's `MongoDict.close()` closes the `MongoClient` it was given, even one supplied through `connection=`. A client shared with a `CacheManager` therefore needs `CachedSession(..., autoclose=False)` in `main`.
- `MongoCache` has no hook for the storage class, so `CachedMongoCache.__init__` calls `BaseCache.__init__` directly and rebuilds both storages.
