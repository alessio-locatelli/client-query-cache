# Tasks

## 1. Measurement harness

- [x] 1.1 Add `research/process_memory/measure.py` as described in [design decisions 1–3](design.md#decisions), with `run`, `child`, and `summarize` subcommands. Verify that `source scripts/testcontainers-bridge.sh && uv run -- python -m research.process_memory.measure run --runs 1 --scenarios partial-cursors --output benchmark-reports/process-memory/smoke.json` prints one table row per API and phase, and that `uv run -- prek run --files research/process_memory/measure.py` passes.
- [ ] 1.2 Record the pre-fix baseline from a disposable worktree of the parent commit (`git worktree add --detach <dir> HEAD`, copy the harness, `uv sync`), running `run --runs 5 --scenarios documents result-sets small-entries large-keys partial-cursors --output <path>/baseline.json`. Verify that every cell has five runs, then remove the worktree with `git worktree remove`.

## 2. Per-entry metadata

- [ ] 2.1 Change `IdentityState.alias_keys` in `src/client_query_cache/_core/namespace.py` to a `frozenset` defaulting to `frozenset()`, and replace every mutation in `src/client_query_cache/_core/manager.py` (`record_write`, `_bump_epoch_and_reclaim`, `_publish_alias_locked`, `_discard_alias_locked`) with reassignment. Add parametrized tests in `tests/core/test_aliases_and_isolation.py` asserting that an identity admitted without an alias holds the shared empty `frozenset`, and that alias reassignment, a write to the identity, and namespace clearing leave earlier identities with an empty alias set while the alias resolves only to its current identity. Verify with `just pytest -- tests/core -q`.
- [ ] 2.2 Make `begin_identity_admission()` and `capture_namespace_generation()` return captures holding the registered `NamespaceState.namespace`. Add a test in `tests/core/test_lru_storage.py` or the closest existing core test module that admits identity, namespace, and unique-key entries through distinct equal `NamespaceId` objects and asserts that every resident entry and LRU key references one instance and that lookups through a new equal `NamespaceId` hit. Verify with `just pytest -- tests/core -q`.
- [ ] 2.3 Run `just test-memory` and verify both churn cases pass under their existing ceilings.
- [ ] 2.4 Rerun the harness from the working tree with `run --runs 5 --output benchmark-reports/process-memory/final.json` (all scenarios, including `cycles`), and repeat the per-entry `tracemalloc` attribution described in [design.md](design.md#context) for one-predicate generic `find_one` and `_id` reads before and after the change. Verify that cached-minus-direct RSS per entry fell for `documents` and `small-entries` and that `cycles` shows a stable filled peak and object count.

## 3. Evidence and documentation

- [ ] 3.1 Write `reports/process-memory/summary.md` with the environment, reproduction commands, final cached-minus-direct tables, baseline comparison, per-entry attribution, cost classification, unchanged existing behavior, limitations, and a link to [issue #245](https://github.com/alessio-locatelli/client-query-cache/issues/245), and link it from `docs/development/index.md`. Verify each figure against `summarize` output for `final.json` and `baseline.json`.
- [ ] 3.2 Add measured memory beyond the BSON budget and retention after release to `docs/user/operations/deployment.md#capacity-estimation`, link it from the limits in `docs/user/reference/api.md`, and update the matching `context7.json` rules. Verify against [the delta spec](specs/public-library-documentation/spec.md) and run `just docs-build`.
- [ ] 3.3 Add one `CHANGELOG.md` entry for the reduced per-document bookkeeping, following the policy comment at the top of the file.

## 4. Code Quality

- [ ] 4.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure that the "Writing Tests" guidelines from `AGENTS.md` are applied, including test parametrization.
- [ ] 4.2 If you are Claude Code, confirm that you added no new prose to the code (all "why" explanations must go in the specs and commit bodies). OpenAI Codex is exempt from this rule because it understands the difference between garbage and valuable code comments.
