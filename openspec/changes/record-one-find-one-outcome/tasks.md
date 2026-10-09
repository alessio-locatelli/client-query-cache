# Tasks

## 1. Core lookup

- [x] 1.1 Implement the deferred-miss lookup and the public miss recorder described in design.md (`LookupResult` in `src/client_query_cache/_core/entries.py`, `CacheCore` in `src/client_query_cache/_core/manager.py`). Both miss branches of `lookup_namespace()` honor the deferral; hits and the stream-unavailable bypass branch keep their current accounting. Verify with core tests in `tests/core/` (extend an existing lookup test module, parametrized over absent and stale-generation entries) asserting that a deferred lookup leaves misses unchanged and sets `deferred_miss`, that a later `record_miss()` adds exactly one miss, and that a deferred lookup on an unavailable database records one bypass with `deferred_miss` false.

## 2. Facades

- [x] 2.1 In `find_one()` of `src/client_query_cache/asynchronous/collection.py` and `src/client_query_cache/synchronous/collection.py`, defer the generic lookup's miss exactly when the read will run unique-key discovery after a miss, and record the deferred miss when discovery finds no unique key. Keep both files structurally identical. Verify with `just pytest tests/synchronous/test_unique_key_reads.py tests/asynchronous/test_unique_key_reads.py`.
- [x] 2.2 In both `tests/synchronous/test_unique_key_reads.py` and `tests/asynchronous/test_unique_key_reads.py`, assert the scenarios in `specs/cached-read-api/spec.md`: in `test_unique_key_read_is_cached_after_the_first_lookup`, snapshot before the first read and assert one miss and no hit for it; in `test_generic_read_caches_when_index_inspection_fails`, assert one miss for the first read and one hit, no miss, for the second; add a parametrized cold-read case for a filter that matches no unique index (for example a unique index on a different field) asserting one miss. The unique-key assertions must fail when task 2.1 is reverted, and the no-match and probe-failure assertions must fail when the deferred miss is never recorded.

## 3. Documentation and example

- [x] 3.1 In `docs/user/operations/monitoring.md`, delete the sentence that cites issue #213 and state that each eligible read records at most one hit or miss, while one request can still record more than one bypass. Verify with `just lint`.
- [x] 3.2 In `examples/fastapi_catalogue_example.py`, make `recorded_outcome()` classify only exactly one miss, with no hit or bypass, as a miss, so that any other count is reported as unexpected. Verify with `just examples` (or `just pytest tests/examples`).
- [x] 3.3 Add a `### Bug fixes` entry under `## Unreleased` in `CHANGELOG.md` saying that the first `find_one()` matching a unique index records one cache miss instead of two in manager snapshots and OpenTelemetry metrics.

## 4. Performance

- [x] 4.1 Run the hot-path guard against `main` and record its per-case base/head timings and decisions in the implementation commit body: `uv run -- python -m benchmarks.stream_cost.guard_check --base-revision main --head-revision HEAD --work-dir /tmp/agents/issue-213/guard --output /tmp/agents/issue-213/guard.report.json`. The cold unique-key path is not covered by the guard; additionally time 1,000 cold unique-key `find_one()` calls on fresh managers with a throwaway script under `/tmp/agents/issue-213/` on both revisions and record the result and the command in the commit body.

## 5. Code Quality

- [x] 5.1 Scan every test file edited or added in this change, including pre-existing tests in those files, and apply the "Writing tests" guidelines from `AGENTS.md`, including parametrization.
- [x] 5.2 If you are Claude Code, confirm that you added no new prose to the code (all "why" explanations must go in the specs and commit bodies).
