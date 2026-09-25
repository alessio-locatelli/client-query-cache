# Proposal

## Why

`_core/manager.py`'s `CacheCore` and its supporting pure-Python modules (`canonical.py`, `order_sensitive_keys.py`, `lru.py`, `unique_keys.py`, `projection.py`) carry invariants — canonicalization idempotence, generation-ordered admission, budget accounting, unique-key field matching — that today are checked only against a small number of hand-picked examples and, in `test_admission_contracts.py`, a single fixed 8-thread/50-iteration operation sequence. `hypothesis>=6.168.0` is already a dev dependency and `.hypothesis/` is already gitignored, but it is not imported anywhere in the codebase. Property-based testing can explore the input and operation-ordering space these modules were designed for and shrink any failure to a minimal reproducer, which the current fixed examples cannot do.

## What Changes

- Add Hypothesis-based property tests for `canonicalize` and `order_sensitive_key`/`order_sensitive_discriminator_key` (idempotence, dict-key-order invariance, bool/int distinction) alongside the existing fixed-example tests in `tests/core/test_canonical.py` and `tests/core/test_order_sensitive_keys.py`.
- Add a Hypothesis property test for `ensure_id_present_for_resolution` in `tests/core/test_projection.py` asserting the mixed-inclusion/exclusion invariant across generated projection shapes.
- Add a `hypothesis.stateful.RuleBasedStateMachine` for `WeightedLru` in `tests/core/test_lru.py` covering `conditional_put`/`touch`/`peek`/`remove_exact` and asserting the budget and generation-ordering invariants.
- Add a `hypothesis.stateful.RuleBasedStateMachine` for `CacheCore` (new `tests/core/test_manager_state_machine.py`) driving identity/namespace admission, lookup, write, and clear operations over a small key alphabet, asserting the same staleness/leak invariants `test_admission_contracts.py` and `test_entry_kinds.py` currently check by hand; the existing fixed adversarial and concurrency tests are kept as-is.
- Add a property test for `discover_unique_keys`/`match_unique_key` field-set matching in `tests/core/test_unique_keys.py` covering generated field-name sets and filter shapes.
- Document the project's Hypothesis-vs-Faker-vs-fixed-value decision rule in `AGENTS.md` so future tests apply it consistently.

Not in scope for this change (see design.md for rationale): a `route_change_event` stateful machine, `read_validation.py` unsafe-key generators, and any Hypothesis use against live MongoDB in the `synchronous`/`asynchronous` integration suites.

## Capabilities

### New Capabilities

- `property-based-testing`: defines which pure, invariant-bearing `_core` modules require Hypothesis property/stateful coverage in addition to example-based tests, and the decision rule for choosing Hypothesis vs. Faker vs. fixed values.

### Modified Capabilities

None. This change adds test coverage only; no production behavior changes.

## Impact

- Affected code: `tests/core/test_canonical.py`, `tests/core/test_order_sensitive_keys.py`, `tests/core/test_projection.py`, `tests/core/test_lru.py`, `tests/core/test_unique_keys.py`, and a new `tests/core/test_manager_state_machine.py`. No changes to `src/mongo_client_cache/`.
- Dependencies: none added — `hypothesis` is already a dev dependency.
- Docs: `AGENTS.md` gains a short "Faker vs. Hypothesis vs. fixed values" guideline in the existing "Writing tests" section.
