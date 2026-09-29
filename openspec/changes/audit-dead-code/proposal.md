# Proposal

## Why

Two mechanically distinct kinds of dead weight have accumulated in `src/`: public `CacheCore` methods exercised only by unit tests (never by the synchronous/asynchronous facades or any other production path), and conditional branches guarding for value shapes that real MongoDB/pymongo data never produces, exercised only because a unit test constructs a contrived value. Confirmed examples: `CacheCore.lifecycle_state` and `CacheCore.lookup_by_alias` in `src/client_query_cache/_core/manager.py` have zero references outside `tests/core/`, `tests/asynchronous/`, and `tests/synchronous/` (all `pytest.mark.unit`); production code resolves aliases via the separate `resolve_alias` + `lookup_identity` pair instead. Separately, `_wall_time_seconds` in `src/client_query_cache/_core/stream_events.py` guards `if value.tzinfo is None: value = value.replace(tzinfo=datetime.UTC)` — replacing the guard with `assert value.tzinfo is None` and removing the alternate branch only fails 3 benchmark tests in `tests/benchmark/stream_cost/test_guard_workload_integration.py` that inject a tz-aware value; the full integration and e2e suites, which exercise real change-stream `wallTime` values, pass unchanged. Both patterns bloat the code that humans and coding agents must read, and the type/shape guards specifically invite false assumptions about what MongoDB can actually return.

## What Changes

- Run the non-unit test suite (integration, e2e, benchmark) under coverage and cross-reference against a full-suite run to identify `src/` symbols and branches reached only by unit tests; delete confirmed dead symbols (starting with the two found above) and update or remove the unit tests that exclusively exercised them.
- Audit conditionals in `src/` that guard on the shape or type of a value sourced from MongoDB, pymongo, or bson (change-stream events, driver return values, BSON-decoded documents) to determine whether the guarded alternate branch is reachable with real data, using the assert-and-rerun-non-unit-suite technique demonstrated for `_wall_time_seconds`.
- For each branch confirmed always-true (or always-false) against real data: remove the dead alternate branch, replacing the guard with an `assert` only where the invariant is non-obvious and worth documenting as a contract; delete unit tests that only existed to hit the removed branch, and add or keep a direct test only where the retained assertion's failure mode is not already covered.
- Where a removed branch's condition was hiding a real, currently-unhandled input class (rather than being provably unreachable), leave the code unchanged and record the finding instead of deleting it.

## Capabilities

No specification delta: this removes internal dead code and inlines proven-always-true guards as assertions, with no change to any documented library behavior, public API, or runtime cache semantics.

## Impact

- Affected files: `src/client_query_cache/_core/manager.py` (`lifecycle_state`, `lookup_by_alias`), `src/client_query_cache/_core/stream_events.py` (`_wall_time_seconds`), and any other `src/` module where the audit confirms a test-only symbol or an always-true/always-false branch.
- Corresponding unit tests in `tests/core/`, `tests/asynchronous/`, `tests/synchronous/`, and `tests/benchmark/` that exist only to exercise removed code.
- No public API, dependency, or runtime behavior changes for callers who only exercise real MongoDB-backed paths.
