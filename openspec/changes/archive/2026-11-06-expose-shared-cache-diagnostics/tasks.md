# Tasks

## 1. Worker diagnostics

- [x] 1.1 Create `src/client_query_cache/_shared/diagnostics.py` with the reason types and the by-value lookup of design D3, and make the adapter constants and the owner's gate and `namespace_capacity` strings take their values from the enum. Add `tests/shared_cache/test_diagnostics.py` covering the vocabulary against `BypassReason` and the gate. Update the tests and `benchmarks/` that pin old spellings (`rg -n '"progress-expired"|unportable-key|owner-unavailable|shared-scope|metadata-refresh|stream-unavailable|database-not-authorized|stream-starting' tests benchmarks`). Verify with `just pytest tests/shared_cache`.
- [x] 1.2 Move statistics into `LocalObservation.snapshot()` per design D3, delegate both managers' `snapshot()` to it, extend `SharedCacheStatistics` and fix its call sites (`rg -n 'SharedCacheStatistics' src benchmarks tests`). Move `SharedCacheStatistics` into `diagnostics.py` so the synchronous and asyncio packages can export it, and give `benchmarks/public_shared_cache.py` its own counts type. Test one reason per case through the public managers in `tests/shared_cache/test_public.py` (session, missing collection, unlisted database, locale collation, unsupported options, stopped owner) and the oversized result in `test_adapter_paths.py`; in `test_diagnostics.py` test the unknown-reason fallback, the totals invariant with Hypothesis and concurrent recording against snapshots. Verify with `just pytest tests/shared_cache`.

## 2. Owner diagnostics

- [x] 2.1 Extend `SharedCacheOwner.observation()` in `coordinator.py` as design D4 describes (new `_started` slot; namespace count from `core.namespaces_for_database`). Test in `tests/shared_cache/test_owner.py`: each of the six statuses, and a parametrized pin of every status to the reason `_gate` returns for the same state. Verify with `just pytest tests/shared_cache/test_owner.py`.
- [x] 2.2 In `diagnostics.py` add the owner types and a pure mapper from the wire reply (cache bytes from `cache.used_bytes` and `cache.budget_bytes`, index entries from `shared_index.published`, connections from `connections`, evictions from `cache.evictions`, rejected connections from `counters.connections_rejected`, the rest from 2.1), annotated with the `client_query_cache._types` aliases. Scale the server's frame overhead with the configured database names (design Risks). Add `owner_snapshot()` to `SharedCacheManager` (`_check_open()`, then `endpoint.request({"op": "observe"})`) and an `async` twin on `AsyncSharedCacheManager`. Test every scenario of the owner-diagnostics requirements in `tests/shared_cache/test_public.py` for sync and asyncio with a real `SharedCacheServer`, polling for the first non-`None` answer after `restart()`; compare `endpoint.counters.requests` to prove no extra request; also test that the smallest valid `SharedCacheConfig` still fits the reply frame. Verify with `just pytest tests/shared_cache/test_public.py`.
- [x] 2.3 Add pressure and stream-status tests with small `SharedCacheConfig` values in `test_public.py`: a byte budget that evicts, `namespaces=1` with a second collection and `connections=2` with a third attach. Trigger `startup_failed` with `SharedCacheServer("mongodb://127.0.0.1:1", (database,), client_options={"serverSelectionTimeoutMS": 200})`. In `tests/shared_cache/test_adapter_paths.py` extend the `pause-watch` scenario to trigger `progress_expired` and recovery. Verify with `just pytest tests/shared_cache`.
- [x] 2.4 Export the new types from `client_query_cache/shared.py`, `client_query_cache/__init__.py`, `synchronous/__init__.py` and `asynchronous/__init__.py`, and extend `tests/test_public_surface.py` and `tests/test_public_annotations.py`. Verify with `just pytest tests/test_public_surface.py tests/test_public_annotations.py`.

## 3. OpenTelemetry

- [x] 3.1 In `otel.py`, make `register_cache_metrics` select the worker-scope instruments for the two adapter manager classes (design D5). Extend `tests/test_otel.py` for both shared managers attached to an absent owner, covering the `otel-metrics` scenarios; the existing process-local tests pin their unchanged output. Verify with `just pytest tests/test_otel.py tests/test_docs_otel_example.py`.

## 4. Documentation and example

- [x] 4.1 Rewrite "Shared manager diagnostics" in `docs/user/operations/monitoring.md`: both snapshots, a symptom table based on design D4, the `healthy` limit, telemetry scope with a link to #424, and a worker health-check snippet run as written by `test_documented_health_check_runs_as_written`. Remove the sentence saying the bridge does not support shared managers. Update the stale descriptions found by `rg -n 'SharedCacheStatistics|worker-local|snapshot\(\)' docs/user`. Verify with `just docs-build` and `just lint`.
- [x] 4.2 Add the `/diagnostics` route and self-check assertions of design D6 to `examples/fastapi_shared_example.py`, then update `docs/user/examples/fastapi-shared.md` and `examples/README.md` where they list the checks. Verify with `just examples` and `just typecheck-examples`.
- [x] 4.3 Update `context7.json` with at most one rule covering the `None` result and the request cost of `owner_snapshot()`, and add the Unreleased `CHANGELOG.md` entry. Verify with `just lint`.

## 5. Performance

- [x] 5.1 Compare hit and miss latency on `main` and on this branch with `.venv/bin/python -m benchmarks.public_shared_cache --method find_one --hot-keys 1024 --document-bytes 4096 --samples 16384 --repetitions 1 --models sync --paths shared --workloads hot cold --output /tmp/agents/diagnostics/<revision>.json`, running `main` from a worktree with `PYTHONPATH=<worktree>/src` and the built extension copied in. Alternate revisions five times, compare medians, investigate any reproducible slowdown, and record commands and medians in the implementation commit body.

## 6. Code Quality

- [x] 6.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure that the "Writing tests" guidelines from `AGENTS.md` are applied, including test parametrization.
- [x] 6.2 If you are Claude Code, confirm that you added no new prose to the code (all "why" explanations must go in the specs and commit bodies).
