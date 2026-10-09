# Tasks

Define each alias from the design's alias table in the same group that first uses it. Vulture rejects an alias that has no use. To list candidate comments in a tree, run `rg -n '#\s' --type py <tree> | rg -v '#\s*(noqa|type:|pragma|nosec|pytriage)'`, then classify each clause with the design's prose rules.

## 1. Dependency, alias module, and library

- [ ] 1.1 Before any code edit, record a baseline: the median of ten runs of `uv run -- python -X importtime -c 'import client_query_cache' 2>&1 | tail -1`. Keep the result for the group 4 commit body. Then run `uv add 'annotated-types>=0.8.0'` so the requirement lands in `[project].dependencies`, not a dependency group. Verify with `uv lock --check`.
- [ ] 1.2 Create `src/client_query_cache/_types.py` without comments, and apply the design's "Public interfaces" decision in `_core/manager.py`, `_core/stream_cost.py`, `_core/snapshots.py`, and both `manager.py` modules (`synchronous/` and `asynchronous/`). Do not change validation code. Verify that `just lint` passes, and that Ruff places every alias import under `TYPE_CHECKING`.
- [ ] 1.3 Replace type prose in the remaining `src/` comments that the listing command finds, keeping each synchronous/asynchronous pair identical. Verify that `just lint` passes and that the listing shows only meaning clauses and non-type prose in `src/`.
- [ ] 1.4 Add the `property-based-testing` delta's property tests. In `tests/core/test_lru_storage.py`, cover `CacheCoreConfig` budgets drawn from `st.from_type(PositiveInt)` and ordered so the entry size does not exceed the budget. In `tests/core/test_stream_cost.py`, cover all three `LagCaptureWindowConfig` fields. In `tests/core/test_stream_options.py`, turn the parametrized valid await-time test into a property over `st.from_type(MaxAwaitTimeMs)`, keeping `1` and `MAX_AWAIT_TIME_MS` as `@example`s. Check whether `validate-cache-numeric-configuration` has already changed these files, and place the properties beside its boundary tests. Verify that the targeted tests pass with `just pytest tests/core/test_lru_storage.py tests/core/test_stream_cost.py tests/core/test_stream_options.py`, and that a temporary widening of `PositiveInt` to `Ge(0)` makes the budget property fail. Revert the widening afterwards.
- [ ] 1.5 Add one bullet to the "General" list in `AGENTS.md` that names `client_query_cache._types` as the source of constrained, BSON, and JSON aliases. The bullet must say that bare annotations need no permissive prose and that metadata is not validation. Do not link to OpenSpec paths. Verify that `just lint`, including lychee and markdownlint, passes.

## 2. Tests and scripts

- [ ] 2.1 Apply the `type-annotations` delta's BSON and JSON requirement in `tests/`. Use `BsonDict` for document type arguments of clients, collections, cached collections, managers, cursors, and change events, and for inserted, read, and expected documents. Use `JsonDict` for objects passed to `json.dumps` or decoded by `json.loads`. Keep keyword-argument bundles, `**`-unpacked dictionaries, option dictionaries, and `Mapping[...]` parameters unchanged. Replace the local `Document` aliases in `tests/cursor_fixtures.py` and `tests/test_bound_sessions.py`. Resolve the resulting mypy errors by annotating literals with `BsonDict` or narrowing as the design's alias notes allow, never by reintroducing `Any`. Verify that `uv run -- mypy` reports no issues.
- [ ] 2.2 Replace type prose in `tests/` comments that the listing command finds. Test-value comments required by `test-value-conventions` remain. Verify that `just lint` passes and that the listing shows only meaning clauses and non-type prose in `tests/`.
- [ ] 2.3 Apply the design's local alias cleanup to `scripts/build_versioned_docs.py` and `tests/test_build_versioned_docs.py`, and replace any other type prose in `scripts/`. Verify that `uv run --only-group docs -- python -c 'import scripts.build_versioned_docs'` succeeds without the project installed, and that `just pytest tests/test_build_versioned_docs.py` passes.

## 3. Benchmarks

- [ ] 3.1 Apply tasks 2.1 and 2.2 to `benchmarks/`. JSON reports and registered configurations use `JsonDict`. Client and manager document type arguments use `BsonDict`. In `benchmarks/stream_cost/multiprocess_run.py`, keep the `Payload` alias, which also types pickled pipe messages, and drop only its emptiness comment. Verify that `uv run -- mypy` and `just lint` pass, and that the listing shows only meaning clauses and non-type prose in `benchmarks/`.

## 4. Integration

- [ ] 4.1 Repeat the import-time measurement from task 1.1, and run `uv run -- python -c 'import sys, client_query_cache; sys.exit("annotated_types" in sys.modules)'`. Run `uv build` and confirm that the wheel's METADATA lists `Requires-Dist: annotated-types>=0.8.0`. Record the before and after medians and the loaded-module result in the commit body.

## 5. Code Quality

- [ ] 5.1 Scan the entire file for each edited or added test file, including pre-existing tests, and apply AGENTS.md's "Writing tests" guidelines, including parametrization; verify the resulting test diff.
- [ ] 5.2 If implementing with Claude Code, confirm that no new prose was added to code, and that every why explanation is in specs or commit bodies. OpenAI Codex is exempt.
