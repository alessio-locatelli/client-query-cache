# Proposal

## Why

Several test files hand-roll literal values (`"doc-1"`, `"a@example.com"`, `"Ada"`, fixed padding sizes) where the exact value is incidental to the behavior under test, in directories that already have a working Faker-based pattern (`make_fake_document` in `tests/conftest.py`) sitting unused nearby. Meanwhile a few genuinely significant fixed values (e.g. the stress-test tuning constants in `test_admission_contracts.py`, the cache-budget numbers in `test_collection.py`'s `tight_budget_cache_manager` fixture) carry no comment or descriptive name explaining why that specific value was chosen, and no prior commit message fills the gap either. Neither gap is documented as a convention, so both keep recurring as new tests are added.

## What Changes

- Migrate incidental hard-coded document/field values in `tests/synchronous/test_unique_key_reads.py` and `tests/asynchronous/test_unique_key_reads.py` to `make_fake_document`/`faker`, keeping any value that is written once and asserted later as a single reused local variable rather than a value generated twice.
- Migrate incidental hard-coded document values in `tests/synchronous/test_streams_integration.py` and `tests/asynchronous/test_streams_integration.py` to `faker`-generated values, preserving distinct before/after pairs (e.g. an update's new value must differ from the original) and reusing the same generated `_id`/value across a test's write and assertion.
- Add a short inline comment or a named constant to the stress-test tuning parameters in `tests/core/test_admission_contracts.py::test_no_code_path_holds_the_namespace_lock_and_the_lru_lock_at_once` explaining what each controls.
- Add a short inline comment to the `tight_budget_cache_manager` fixture in `tests/synchronous/test_collection.py` (and its asynchronous counterpart) explaining the relationship between the configured budget/entry-size numbers and the fake documents they're meant to admit or reject.
- Document the convention in `AGENTS.md`'s existing "Writing tests" section: an incidental value (exact value doesn't matter) uses `faker`; a value that must stay exact gets a descriptive name, a fixture, a module-level constant, or a short inline comment explaining the choice — unless the rationale is already in the file's git history, in which case no refactor is required.

Not in scope for this change (see design.md for rationale): `tests/core/*` (values there are either already self-documenting, like `"fresh"`/`"stale"`, or trivial placeholders where a fixed literal communicates the test at least as well as a generated one), `tests/benchmark/stream_cost/*` (already has its own descriptive defaults-factory convention for structured config), and `tests/e2e/test_installed_package.py` (a single incidental literal inside a subprocess-executed script with no access to the `faker` fixture; not worth the plumbing for one value).

## Capabilities

### New Capabilities

- `test-value-conventions`: defines when a test value must come from `faker` versus when a fixed value is acceptable, and what a fixed value that must stay exact requires (descriptive name, fixture, constant, comment, or documented git history).

### Modified Capabilities

None. This change touches test code and contributor documentation only; no production behavior changes.

## Impact

- Affected code: `tests/synchronous/test_unique_key_reads.py`, `tests/asynchronous/test_unique_key_reads.py`, `tests/synchronous/test_streams_integration.py`, `tests/asynchronous/test_streams_integration.py`, `tests/core/test_admission_contracts.py`, `tests/synchronous/test_collection.py`, `tests/asynchronous/test_collection.py`. No changes to `src/mongo_client_cache/`.
- Dependencies: none added — `faker` is already a dev dependency and already used elsewhere in the suite.
- Docs: `AGENTS.md` gains a short "incidental vs. significant test values" guideline in the existing "Writing tests" section.
