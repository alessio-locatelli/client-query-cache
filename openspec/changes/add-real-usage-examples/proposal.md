# Proposal

## Why

The test suite proves the cache is correct, but it cannot show whether the public interface is pleasant or even workable when a real library adopts it. Integrating the cache into real third-party projects that already store data in MongoDB exposes interface and architecture problems that isolated tests miss, and gives new users complete, copyable starting points.

## What Changes

- Add a top-level `examples/` directory of complete, runnable programs that integrate `client-query-cache` into real third-party libraries that already use MongoDB as storage.
- Add a `requests-cache` example: a `requests_cache` MongoDB backend whose storage reads go through a `CacheManager` cached view while writes stay on PyMongo. The example runs against a local in-process HTTP server, so it works offline and reports origin hits and cache statistics that show both caching and change-stream invalidation.
- Plan an `aiohttp-client-cache` example with the same shape on `pymongo.AsyncMongoClient`. Its implementation is **blocked** until upstream replaces Motor with PyMongo's asyncio client ([aiohttp-client-cache#415](https://github.com/requests-cache/aiohttp-client-cache/issues/415)): the upstream MongoDB backend currently requires Motor, which `client-query-cache` does not support, and a throwaway custom backend would be discarded once upstream lands.
- Extend the implementation backlog in priority order with Celery's MongoDB result backend, py-abac's MongoDB policy storage, and Eve's MongoDB data layer. Each target starts with released-version and adapter feasibility verification; completed examples follow the existing dependency, observability, verification, and documentation requirements.
- Investigate Hyperopt `MongoTrials` after those targets. Its inspected upstream code uses legacy PyMongo methods, so compatibility with the project's supported environment must be established before committing to a runnable example.
- Declare each example's third-party dependencies inline in the example file (PEP 723 script metadata) and run it with `uv run examples/<example>.py`, which provisions them ephemerally next to the working-tree `client_query_cache`; `pyproject.toml` and `uv.lock` gain no new dependencies.
- Add an integration test that runs every example as a subprocess against the disposable replica set, so CI catches examples broken by library changes, and a `just examples` recipe that runs just that test.
- Type-check the examples with their third-party libraries available, separately from the main mypy run.
- Record the public-interface and architecture friction found while writing each example. Each confirmed problem is fixed in its own follow-up change, not in this one.
- Link the examples from the README.

## Capabilities

### New Capabilities

- `usage-examples`: complete, runnable integrations of `client-query-cache` into real third-party libraries, how they are run without adding project dependencies, and how they are kept working.

### Modified Capabilities

None.

## Impact

- New `examples/` directory, `justfile` recipe, integration test module, an examples type-check step in `just lint` and the Python validation workflow, and README/CONTRIBUTING/CHANGELOG entries.
- No change to the `client_query_cache` package, its public API, or its runtime or development dependencies. The integration test and `just examples` download the example libraries into uv's cache on first use, which needs network access.
- The change stays open until the blocked `aiohttp-client-cache` example and the added Celery, py-abac, and Eve work are resolved. Feasibility investigations must record concrete blockers; an unsuitable target requires an explicit planning revision rather than a silently skipped implementation. Hyperopt investigation completes with a documented feasibility decision, not a mandatory runnable example.
