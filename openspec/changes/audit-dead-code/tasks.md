# Tasks

## 1. Coverage-based dead-symbol removal

- [ ] 1.1 Run `source scripts/testcontainers-bridge.sh && uv run --env-file=".env" -- coverage run -m pytest -m 'not unit'`, then `uv run -- coverage report -m --omit 'tests/*' --include 'src/*'`. Record every `src/` file the report lists with `Missing` line numbers.
- [ ] 1.2 For each `Missing` line range from 1.1, open that file and identify the enclosing top-level `def`/method. Confirm the list includes at least `CacheCore.lifecycle_state` (`src/client_query_cache/_core/manager.py:279-280`) and `CacheCore.lookup_by_alias` (`src/client_query_cache/_core/manager.py:821-849`).
- [ ] 1.3 For each candidate from 1.2, run `rg -n "<symbol_name>" README.md docs/`; if it is documented there as public API, drop it from the deletion list and note "kept: documented public API in `<file>`" instead of deleting it.
- [ ] 1.4 `Missing` under the non-unit suites only proves those specific suites don't exercise the candidate — it does not by itself prove no production code calls it (a real path can simply lack integration/e2e/benchmark coverage). For each remaining candidate, run `rg -n "<symbol_name>" src/` and open every match outside the candidate's own definition; confirm each match is either the candidate's own internal use (e.g. a helper calling itself) or genuinely a different symbol that happens to share the name (as with the three unrelated `close` methods noted in design.md). If any match is a real production (`src/`) call site for the candidate itself, drop it from the deletion list and note "kept: called from `<file>:<line>`" instead of deleting it.
- [ ] 1.5 Delete each candidate that survives 1.3 and 1.4, then run `rg -n "<symbol_name>" tests/` to find every referencing test file and delete or edit out the parts that exercised the removed symbol.
- [ ] 1.6 Verify: `uv run -- mypy` (no unresolved references), `uv run -- pytest -m unit` (passes), then rerun the two commands from 1.1 and confirm the deleted symbols no longer appear in the report at all.

## 2. Dynamic audit: driver-sourced value guards in `_core`

Do not touch `_core/stream_events.py`'s `_wall_time_seconds` or `_core/projection.py`'s `without_id` — design.md's audit inventory classifies both guards as depending on a caller-configurable `CodecOptions` setting (`tz_aware`/`tzinfo` for the former, custom type decoders for the latter), not on an impossible MongoDB response shape; this project's non-unit suites passing after removing either guard would not prove it dead, only that these suites don't happen to configure that setting differently.

- [ ] 2.1 In `src/client_query_cache/_core/collection_metadata.py`, `interpret_list_collections_entry`: temporarily change `if collection_type not in {"collection", "view", "timeseries"}: return None` to `assert collection_type in {"collection", "view", "timeseries"}` and run `just test-integration` and `just test-e2e`. If both pass, delete the temporary `assert` and the branch, returning a `CollectionProbeResult` unconditionally after the `entry is None` check. If either suite fails, revert to the original branch and record which real `listCollections` entry type triggered it.
- [ ] 2.2 In `src/client_query_cache/_core/unique_keys.py`, `_is_eligible_index`/`discover_unique_keys`: convert `index_spec.get("key", {})` to `index_spec["key"]` guarded by `try`/`except KeyError`, and run `just test-integration` and `just test-e2e`. If the `except KeyError` branch is never hit, delete it and keep the direct subscription (per design.md, `key` is a mandatory index-spec field). Leave `index_spec.get("unique", False)` and `index_spec.get("sparse", False)` unchanged — design.md's audit inventory already classifies both as real (MongoDB omits both when `false`).
- [ ] 2.3 Update or delete unit tests in `tests/core/` that only existed to hit branches removed in 2.1-2.2.

## 3. Code Quality

- [ ] 3.1 Scan every test file touched in tasks 1-2 (including pre-existing tests in those files) and apply the "Writing Tests" guidelines from `AGENTS.md`, including `@pytest.mark.parametrize` where cases share logic.
- [ ] 3.2 Confirm no new prose (docstrings or comments) was added to `src/` during this change, and that no temporary `assert` from task 2 survived into the committed diff.
