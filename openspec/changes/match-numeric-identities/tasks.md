# Tasks

## 1. Baseline and regression tests

- [ ] 1.1 Record the routing baseline on the unchanged code with `uv run python -m timeit -s "from bson import ObjectId; from client_query_cache._core.keys import NamespaceId; from client_query_cache._core.manager import CacheCore; core = CacheCore(); ns = NamespaceId('d', 'c'); identity = ObjectId()" "core.record_write(ns, identity)"`. Repeat it with `identity = {'tenant': 't', 'n': 7}`, and keep both results for the commit body.
- [ ] 1.2 In `tests/synchronous/test_collection.py` and `tests/asynchronous/test_collection.py`, add `test_find_one_by_id_invalidates_numerically_equal_stored_ids`, parametrized over `(stored_id, read_id)`:
  - `(Decimal128("1"), 1)`;
  - `(Decimal128("1E+1"), 10)`;
  - `(Decimal128("0.5"), 0.5)`;
  - `({"n": Decimal128("3")}, {"n": 3})`.

  The test inserts `{"_id": stored_id, "v": <faker word>}` through `collection.raw` and reads `find_one({"_id": read_id})` twice under `_spy_on_driver`, expecting one driver call. It then updates `v` through `independent_writer` with the `stored_id` filter, calls `wait_for_stream_barrier` (or `wait_for_stream_barrier_async`), and asserts that the next read returns the new `v`.

  Also add `test_unequal_numeric_ids_do_not_share_entries`. It inserts documents with the `_id` values `19.99` and `Decimal128("19.99")`, then asserts that each `find_one` by its own `_id` returns its own document on two repetitions.

  Run `just pytest tests/synchronous/test_collection.py tests/asynchronous/test_collection.py -k "numerically_equal or unequal_numeric"`. Before task 2.1, the first test must fail on the cached stale value.

## 2. Exact decimal identities

- [ ] 2.1 Apply design.md D1 in `src/client_query_cache/_core/order_sensitive_keys.py`: when `distinguish_numeric_subtypes` is false, map `bson.decimal128.Decimal128` to `value.to_decimal()`. Add the following tests:
  - In `tests/core/test_order_sensitive_keys.py`, merge `test_order_sensitive_key_treats_float_and_int_as_the_same_identity` and `test_order_sensitive_key_treats_int64_and_int_as_the_same_identity` into one parametrized test over `1.0`, `Int64(1)`, `Decimal128("1")` and `Decimal128("1.0")`, plus `{"n": Decimal128("1")}` against `{"n": 1}`. It asserts equal canonical keys and hashes.
  - In `test_order_sensitive_discriminator_key_distinguishes_equal_valued_numeric_subtypes`, include `Decimal128(str(value))`. The identity key must equal the `int` key, and the discriminator key must remain uncanonicalizable.
  - A parametrized test asserting that `Decimal128("NaN")` and `Decimal128("sNaN")` identities are not canonicalizable.
  - In `tests/core/test_entry_kinds.py`, a test that admits an identity entry for `1` and calls `record_write` with `Decimal128("1")`; the lookup then misses.

  Verify with `just pytest tests/core/test_order_sensitive_keys.py tests/core/test_entry_kinds.py` and the task 1.2 command.

- [ ] 2.2 Rerun both task 1.1 commands, and put both results in the commit body.
- [ ] 2.3 Update the documentation:
  - In the "Cache granularity" bullet of `docs/development/architecture.md`, state that identities match by MongoDB value equality across numeric types.
  - Add a `### Bug fixes` entry under `## Unreleased` in `CHANGELOG.md`, following its editing policy: a cached `_id` read is refreshed after writes to the document even when its stored `_id` is a numerically equal decimal.

  Verify with `just lint`.

## 3. Code Quality

- [ ] 3.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure that the "Writing Tests" guidelines from `AGENTS.md` are applied, including test parametrization.
- [ ] 3.2 If you are Claude Code, confirm that you added no new prose to the code (all "why" explanations must go in the specs and commit bodies). OpenAI Codex is exempt from this rule because it understands the difference between garbage and valuable code comments.
