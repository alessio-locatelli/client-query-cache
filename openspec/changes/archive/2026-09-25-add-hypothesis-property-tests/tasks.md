# Tasks

## 1. Canonicalization and order-sensitive key properties

- [x] 1.1 Add a shallow `st.recursive` BSON-like strategy (none/bool/int/float-no-nan/text leaves, list/dict branches) as a shared helper in `tests/core/test_canonical.py`, and a property test asserting `canonicalize(canonicalize(x)) == canonicalize(x)`; verify with `just pytest tests/core/test_canonical.py -q`.
- [x] 1.2 Add a property test in `tests/core/test_canonical.py` asserting `canonicalize` of a mapping is unchanged when its top-level keys are reordered; verify with `just pytest tests/core/test_canonical.py -q`.
- [x] 1.3 Reuse the strategy from 1.1 (import or duplicate the minimal helper) in `tests/core/test_order_sensitive_keys.py` to add a property test asserting `order_sensitive_key` differs from a reordered mapping's key exactly when relative key order changed; verify with `just pytest tests/core/test_order_sensitive_keys.py -q`.
- [x] 1.4 Add a property test in `tests/core/test_canonical.py`, generating `bool` and `int` values (including equal-valued pairs like `True`/`1`), asserting `canonicalize(bool_value)` never equals `canonicalize` of any generated `int` value; verify with `just pytest tests/core/test_canonical.py -q`.
- [x] 1.5 Add a property test in `tests/core/test_order_sensitive_keys.py`, generating equal-valued `int`/`float`/`bson.int64.Int64` values, asserting `order_sensitive_discriminator_key` distinguishes all three from each other while `order_sensitive_key` treats them as equal; verify with `just pytest tests/core/test_order_sensitive_keys.py -q`.

## 2. Projection normalization property

- [x] 2.1 Add a Hypothesis strategy for projection dicts (arbitrary field names, values from `{0, 1, True, False}`, optional `_id` entry) in `tests/core/test_projection.py` and a property test asserting `ensure_id_present_for_resolution` never returns a mixed inclusion/exclusion projection; verify with `just pytest tests/core/test_projection.py -q`.

## 3. Weighted LRU stateful coverage

- [x] 3.1 Add a `RuleBasedStateMachine` subclass in `tests/core/test_lru.py` with rules for `conditional_put`, `touch`, `peek`, and `remove_exact` over a `Bundle` seeded from a small fixed set of keys and generation keys, and an `@invariant` asserting `snapshot_usage()` never exceeds the configured `shared_budget_bytes`; verify with `just pytest tests/core/test_lru.py -q`.
- [x] 3.2 Add an `@invariant` to the same state machine asserting a resident entry's generation key is never older than any generation key most recently submitted for that same cache key; verify with `just pytest tests/core/test_lru.py -q`.

## 4. Cache core stateful coverage

- [x] 4.1 Create `tests/core/test_manager_state_machine.py` with a `RuleBasedStateMachine` driving `CacheCore`'s `begin_identity_admission`/`admit_identity`/`discard_identity_admission`, `capture_namespace_generation`/`admit_namespace`, `record_write`, `clear_namespace`, `lookup_identity`, and `lookup_namespace` over a `Bundle` seeded from 3-4 fixed identities across 2 fixed namespaces; verify the file collects and runs with `just pytest tests/core/test_manager_state_machine.py -q`.
- [x] 4.2 Add an `@invariant` asserting no `lookup_identity`/`lookup_namespace` call returns a value the model has already superseded by a later `record_write` or `clear_namespace` for that key; verify with `just pytest tests/core/test_manager_state_machine.py -q`.
- [x] 4.3 Add an `@invariant` asserting the number of resident entries `CacheCore` reports (via its existing inspection surface) matches the model's count of keys admitted since their last clear; verify with `just pytest tests/core/test_manager_state_machine.py -q`.

## 5. Unique-key matching property

- [x] 5.1 Add a Hypothesis strategy generating a `UniqueKeyDefinition` (small field-name set, optional collation) alongside a filter dict (matching fields, extra fields, or missing fields, with equality or operator values) in `tests/core/test_unique_keys.py`, and a property test asserting `match_unique_key` matches if and only if the filter's field set and collation equal the definition's and every field carries a plain equality value; verify with `just pytest tests/core/test_unique_keys.py -q`.
- [x] 5.2 Add a Hypothesis strategy generating index spec dicts (a field-name-keyed `key` mapping with plain or `"hashed"` values, and independently chosen `unique`/`sparse`/`partialFilterExpression`-presence flags) in `tests/core/test_unique_keys.py`, and a property test asserting `discover_unique_keys` includes an index if and only if it is `unique`, not `sparse`, has no `partialFilterExpression`, and has no `"hashed"` key value; verify with `just pytest tests/core/test_unique_keys.py -q`.

## 6. Contributor guidance

- [x] 6.1 Add a short rule to `AGENTS.md`'s "Writing tests" section: use Hypothesis for invariants and operation-ordering over a real input space, `faker` for realistic single-instance data, fixed values when the exact input matters to the test; verify by reading the rendered section.

## 7. Code Quality

- [x] 7.1 Scan every test file touched in groups 1-5 and confirm the "Writing Tests" guidelines from `AGENTS.md` are applied, including `@pytest.mark.parametrize` for same-logic cases and fixture-based (not try/finally) cleanup where applicable.
- [x] 7.2 Confirm no new prose/comments were added to test or source code; all rationale lives in this change's specs/design and the commit bodies.
