# Tasks

## 1. Unique-key read tests

- [ ] 1.1 In `tests/synchronous/test_unique_key_reads.py`, replace the repeated `{"_id": "doc-1"/"doc-2", "email": "a@example.com"/"b@example.com", "name": "Ada"}`-style literals with `faker`-generated `_id`, email, and name values, binding each generated value to a local variable reused across the test's write and its later `find_one`/assertion; verify with `just pytest tests/synchronous/test_unique_key_reads.py -q`.
- [ ] 1.2 Apply the same replacement to `tests/asynchronous/test_unique_key_reads.py`; verify with `just pytest tests/asynchronous/test_unique_key_reads.py -q`.

## 2. Change-stream integration tests

- [ ] 2.1 In `tests/synchronous/test_streams_integration.py`, replace the repeated `"doc-1"`/`"doc-2"` identity literals and `{"v": 1}` → `{"v": 2}` before/after pairs with `faker`-generated values, reusing one generated identity across each test's MongoDB write, `CacheCore` identity-admission calls, and lookup assertions, and deriving each "after" value from its "before" value so the pair stays distinct; verify with `just pytest tests/synchronous/test_streams_integration.py -q`.
- [ ] 2.2 Apply the same replacement to `tests/asynchronous/test_streams_integration.py`; verify with `just pytest tests/asynchronous/test_streams_integration.py -q`.

## 3. Undocumented significant values

- [ ] 3.1 Add a short inline comment to `tests/core/test_admission_contracts.py::test_no_code_path_holds_the_namespace_lock_and_the_lru_lock_at_once` explaining what the `8` worker count, `50` iteration count, `% 5`, and `% 10 == 0` each control; verify by reading the updated test.
- [ ] 3.2 Add a short inline comment to `tight_budget_cache_manager` in `tests/synchronous/test_collection.py` and its equivalent in `tests/asynchronous/test_collection.py` explaining why `shared_budget_bytes=200`/`max_entry_bytes=50` were chosen relative to the fake documents the tests using this fixture admit or reject; verify by reading the updated fixtures.

## 4. Contributor guidance

- [ ] 4.1 Add a short rule to `AGENTS.md`'s "Writing tests" section: an incidental value (exact content doesn't matter) comes from `faker`; a value that must stay exact gets a descriptive name, a constant, a fixture, or a short comment explaining the choice, unless the file's git history already documents it; verify by reading the rendered section.

## 5. Code Quality

- [ ] 5.1 Scan every test file touched in groups 1-3 and confirm the "Writing Tests" guidelines from `AGENTS.md` are applied, including `@pytest.mark.parametrize` for same-logic cases and fixture-based (not try/finally) cleanup where applicable.
- [ ] 5.2 Confirm no new prose/comments were added beyond the specific explanatory comments group 3 calls for; all other rationale lives in this change's specs/design and the commit bodies.
