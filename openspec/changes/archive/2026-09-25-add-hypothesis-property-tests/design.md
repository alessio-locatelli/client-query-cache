# Design

## Context

See proposal.md - Why. The candidate modules live under `src/mongo_client_cache/_core/`, are pure Python (no I/O, no MongoDB), and are already organized as mixins (`CacheCore` in `manager.py` composes `_CacheCoreIdentityAdmission`, `_CacheCoreNamespaceAdmission`, `_CacheCoreUniqueKeyAdmission`, `_CacheCoreLookup`, `_CacheCoreNamespaceLifecycle`, etc.). Their existing unit tests (`tests/core/*`, all `pytest.mark.unit`, no container runtime) already probe these invariants by hand: `test_canonical.py` has a 3-example idempotence test, `test_admission_contracts.py` has a fixed 8-thread/50-iteration operation loop, `test_lru.py` has fixed eviction/generation-ordering sequences. `pytest.ini` sets a global `timeout = 30`; `.coveragerc` enforces branch coverage via `covdefaults`.

## Goals / Non-Goals

**Goals:**

- Add Hypothesis property tests for the five pure invariant-bearing surfaces identified in the proposal, each supplementing (not replacing) the existing fixed-example tests.
- Keep every new test at `unit` speed and marker so it runs without a container runtime and fits the existing 30s pytest-timeout budget.
- Use small, explicit strategies (bounded alphabets, `st.recursive` with a shallow max depth) rather than elaborate custom generators, per the user's stated preference.

**Non-Goals:**

- A `route_change_event` stateful machine against a modeled MongoDB (deferred - would require a faithful model of MongoDB semantics and risks re-implementing the SUT; revisit once the `CacheCore` machine below exists and can be reused as the harness).
- Hypothesis generators for `read_validation.py`'s unsafe-key walkers (existing parametrized cases already cover every unsafe key at every nesting position by hand; marginal value is low).
- Hypothesis use in `tests/synchronous/`/`tests/asynchronous/` integration suites against live MongoDB (real value exists for document-shape edge cases, but needs a small explicit `max_examples` to coexist with per-test container round-trips and the global timeout; out of scope here).
- Replacing `tests/conftest.py`'s `make_fake_document` (Faker) or any existing fixed-example parametrize table - both are already the right tool per the report and are left unchanged.

## Decisions

**One `RuleBasedStateMachine` for `WeightedLru`, one for `CacheCore`, kept separate from the existing hand-written concurrency test.** `test_admission_contracts.py::test_no_code_path_holds_the_namespace_lock_and_the_lru_lock_at_once` exercises real thread interleaving to catch lock-order violations - that concern is orthogonal to operation-ordering correctness and stays as-is. The new `CacheCore` machine runs single-threaded and asserts the two invariants from the spec delta (no lookup returns a value staler than the most recent write/clear for its key; admission bookkeeping accounts for exactly the resident entries), which is what the current hand-written sequences in `test_admission_contracts.py` and `test_entry_kinds.py` already check for their specific fixed sequences.

**Small, explicit strategies over `st.text()`/`st.uuids()` for identity and key alphabets.** Both new state machines use a `Bundle` seeded from a handful of `st.sampled_from` keys/namespaces/generation values (e.g. 3-4 distinct identities, 2 namespaces) rather than unbounded text. A stateful machine benefits from a small alphabet because it biases toward the collisions and repeats (same key admitted twice, same namespace cleared then re-admitted) that actually stress compare-and-swap and eviction logic; an unbounded alphabet would mostly generate non-interacting operations.

**`st.recursive` with a shallow `max_leaves` for `canonicalize`/`order_sensitive_key` structures.** Leaves are `none`/`booleans`/`integers`/`floats(allow_nan=False)`/`text`; branches are `lists`/`dictionaries`. NaN and unhashable values are excluded from the strategy (not generated-then-caught) because their rejection behavior is already covered by `test_canonical.py`'s fixed `UnsupportedCacheRequestError` cases and is orthogonal to the idempotence/order invariants under test here.

**No custom Hypothesis settings/profile.** `pytest.ini`'s `timeout = 30` is a per-test wall-clock limit; the default `max_examples=100` against pure in-memory, no-I/O code runs in well under that for every candidate here. A settings override is added only if a specific test is later observed to need one, per the user's "use settings only when there is a demonstrated reason to deviate" instruction - none is demonstrated yet.

**Reproducibility via Hypothesis's own mechanisms.** No manual `random.seed()` or hand-rolled seeding. A failure shrinks to a minimal example/rule sequence and Hypothesis writes it to its example database (`.hypothesis/`, already gitignored) and prints a `@reproduce_failure` / `@example` hint; that is the sole reproduction path, consistent with the user's instruction.

**Contributor guidance lands in `AGENTS.md`'s existing "Writing tests" section**, not a new document, as a short rule: Hypothesis for invariants/operation-ordering over a real input space, Faker for realistic single-instance data, fixed values when the exact input matters to understanding the test.

## Risks / Trade-offs

- [A too-wide alphabet or recursion depth makes a state machine slow or flaky under the 30s per-test timeout] → Start with the small bounded alphabets and shallow recursion described above; only widen if a specific gap is found missing coverage.
- [A hand-modeled invariant in the `CacheCore` machine diverges from the real generation/epoch semantics documented in the `cache-core` spec, producing false failures] → Model only the two invariants stated in the spec delta (staleness, bookkeeping accounting), not full generation/epoch bookkeeping; assert against `CacheCore`'s own public lookup/inspection surface rather than re-deriving expected internal state.
- [Stateful rules gated by preconditions (e.g. "only touch an admitted key") could leave some `CacheCore`/`WeightedLru` branches under-exercised, interacting with the branch-coverage requirement in `test-environment`] → Verify with `just tests_and_coverage` after implementation; the existing fixed-example tests in the same files already exercise the branches property rules would otherwise miss.

## Migration Plan

Not applicable - this is an additive, test-only change with no production code, deployment, or rollback surface. New tests run as part of the existing `unit` tier and the standard `just tests_and_coverage` gate.
