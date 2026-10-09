# Tasks

Define each alias from the design's alias table in the same group that first uses it. Vulture rejects an alias that has no use. To list candidate comments in a tree, run `rg -n '#\s' --type py <tree> | rg -v '#\s*(noqa|type:|pragma|nosec|pytriage)'`, then classify each clause with the design's prose rules.

## 1. Dependency, alias module, and library

- [x] 1.1 Before any code edit, record a baseline: the median of ten runs of `uv run -- python -X importtime -c 'import client_query_cache' 2>&1 | tail -1`. Keep the result for the task 4.1 commit body. Then run `uv add 'annotated-types>=0.8.0'` so the requirement lands in `[project].dependencies`, not a dependency group. Verify with `uv lock --check`.
- [x] 1.2 Add the design's `exempt-modules` setting to `ruff.toml` under `[lint.flake8-type-checking]`. Create `src/client_query_cache/_types.py` without comments. Apply the design's "Public interfaces" decision, including the `record_logical_event_bytes` parameters, in `_core/manager.py`, `_core/stream_cost.py`, `_core/snapshots.py`, and both `manager.py` modules (`synchronous/` and `asynchronous/`), importing aliases at runtime. Do not change validation code. Verify that `just lint` passes.
- [x] 1.3 Replace type prose in the remaining `src/` comments that the listing command finds, keeping each synchronous/asynchronous pair identical. Verify that `just lint` passes and that the listing shows only meaning clauses and non-type prose in `src/`.
- [x] 1.4 Add the `property-based-testing` delta's property tests, deriving every strategy from `typing.get_type_hints(<class>, include_extras=True)` as the design describes. In `tests/core/test_lru_storage.py`, cover `CacheCoreConfig` budgets, ordered so the entry size does not exceed the budget. In `tests/core/test_stream_cost.py`, cover all three `LagCaptureWindowConfig` fields. Check whether `validate-cache-numeric-configuration` has already changed these files, and place the properties beside its boundary tests. Verify that `just pytest tests/core/test_lru_storage.py tests/core/test_stream_cost.py` passes. Then temporarily annotate `CacheCoreConfig.shared_budget_bytes` with `NonNegativeInt`, confirm that the budget property fails, and revert.
- [x] 1.5 Add a test module under `tests/` that parametrizes over every dataclass in the `__all__` of `client_query_cache` and `client_query_cache.asynchronous`, and asserts that `typing.get_type_hints(cls, include_extras=True)` succeeds. Verify that the test passes, and that it fails with `NameError` when an alias import in `_core/snapshots.py` is temporarily moved under `TYPE_CHECKING`. Revert afterwards.
- [x] 1.6 Add one bullet to the "General" list in `AGENTS.md`. It names `client_query_cache._types` as the source of constrained aliases, requires runtime imports of them, and states that bare annotations need no permissive prose and that metadata is not validation. It also restates the design's `cast(...)` rule. Do not link to OpenSpec paths. Verify that `just lint`, including lychee and markdownlint, passes.

## 2. Tests and scripts

- [x] 2.1 Replace type prose in `tests/` comments that the listing command finds. Test-value comments required by `test-value-conventions` remain. Verify that `uv run -- mypy` and `just lint` pass, and that the listing shows only meaning clauses and non-type prose in `tests/`.
- [x] 2.2 Replace type prose in `scripts/` comments that the listing command finds, without importing library aliases. Verify that `uv run --only-group docs -- python -c 'import scripts.build_versioned_docs'` succeeds without the project installed, and that `just pytest tests/test_build_versioned_docs.py` passes.

## 3. Benchmarks

- [x] 3.1 Replace type prose in `benchmarks/` comments that the listing command finds. Verify that `uv run -- mypy` and `just lint` pass, and that the listing shows only meaning clauses and non-type prose in `benchmarks/`.

## 4. Integration

- [x] 4.1 Repeat the import-time measurement from task 1.1. Run `uv build` and confirm that the wheel's METADATA lists `Requires-Dist: annotated-types>=0.8.0`. Record the before and after medians in the commit body.

## 5. Code Quality

- [x] 5.1 Scan the entire file for each edited or added test file, including pre-existing tests, and apply AGENTS.md's "Writing tests" guidelines, including parametrization; verify the resulting test diff.
- [x] 5.2 If implementing with Claude Code, confirm that no new prose was added to code, and that every why explanation is in specs or commit bodies. OpenAI Codex is exempt.
