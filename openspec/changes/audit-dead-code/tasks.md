# Tasks

## 1. Static audit: symbols reached only from `tests/`

- [ ] 1.1 Cross-reference every top-level `def`/`class` in `src/` against call sites outside `tests/` (module-qualified, to rule out name collisions) and produce the full candidate list; confirm it includes at least `CacheCore.lifecycle_state` and `CacheCore.lookup_by_alias` in `src/client_query_cache/_core/manager.py`.
- [ ] 1.2 For each candidate, check `README.md` and `docs/` for a public-API mention; drop from the candidate list (and record why) any symbol documented as public API rather than deleting it.
- [ ] 1.3 Delete each remaining confirmed-dead symbol and the unit tests that exist only to exercise it; verify with `uv run -- mypy` (no now-unused imports or references) and `uv run -- pytest -m unit`.

## 2. Dynamic audit: `_core` branches on driver-sourced values

- [ ] 2.1 In `src/client_query_cache/_core/stream_events.py`, temporarily replace `_wall_time_seconds`'s `if value.tzinfo is None: ...` with `assert value.tzinfo is None` and run `just test-integration`, `just test-e2e`, and `uv run -- pytest tests/benchmark`; once that confirms only `tests/benchmark/stream_cost/test_guard_workload_integration.py`'s hand-built tz-aware fixtures fail, delete the temporary `assert` together with the `replace(tzinfo=...)` branch, leaving an unconditional `value.replace(tzinfo=datetime.UTC).timestamp()`, and update or delete the tests that only existed to hit the removed branch.
- [ ] 2.2 Identify every other conditional in `src/client_query_cache/_core/` that guards the shape of a change-stream event, a driver return value (index specs, collection/database stats, resume tokens), or a bson-decoded value from the server (as opposed to caller-supplied filters, projections, collations, or documents, which are out of scope per design.md); for each, apply the temporary assert-and-rerun technique from task 2.1 and record which branches are proven always-true/always-false.
- [ ] 2.3 Remove each branch confirmed dead in 2.2, deleting the branch and its temporary `assert` outright with no replacement guard, assertion, or comment; verify with `just test-integration`, `just test-e2e`, and `uv run -- pytest tests/benchmark` after each removal, and update or delete unit tests that only existed to hit the removed branch.
- [ ] 2.4 In `src/client_query_cache/_core/unique_keys.py` and `src/client_query_cache/_core/collection_metadata.py`, convert each `.get(key, default)` call on a driver-sourced mapping (index specs from `list_indexes()`, entries from `listCollections`) to direct subscription guarded by `try`/`except KeyError`; run `just test-integration` and `just test-e2e`, and where the `except` branch is never covered, remove it as a confirmed-dead fallback (keeping the direct subscription); where it is covered, keep both branches as-is since the key is genuinely optional.

## 3. Dynamic audit: synchronous/asynchronous facade branches

- [ ] 3.1 Identify conditionals in `src/client_query_cache/synchronous/` and `src/client_query_cache/asynchronous/` (`collection.py`, `database.py`, `manager.py`, `streams.py`) that guard on a pymongo driver return value or internal stream/lifecycle state reachable only through a real change-stream session, distinguishing them from guards over caller-supplied arguments (which are out of scope); apply the temporary assert-and-rerun technique from task 2.1 to each.
- [ ] 3.2 Remove each branch confirmed dead in 3.1, deleting the branch and its temporary `assert` outright with no replacement guard, assertion, or comment; verify with `just test-integration` and `just test-e2e` after each removal (mirroring both the synchronous and asynchronous module when a finding applies to both), and update or delete unit tests that only existed to hit the removed branch.

## 4. Code Quality

- [ ] 4.1 Scan every test file touched in tasks 1-3 (including pre-existing tests in those files) and apply the "Writing Tests" guidelines from `AGENTS.md`, including `@pytest.mark.parametrize` where cases share logic.
- [ ] 4.2 Confirm no new prose (docstrings or comments) was added to `src/` during this change, and that no temporary `assert` from tasks 2-3 survived into the committed diff.
