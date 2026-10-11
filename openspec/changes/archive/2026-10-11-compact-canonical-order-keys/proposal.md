# Proposal

## Why

[Issue #245](https://github.com/alessio-locatelli/client-query-cache/issues/245): `canonicalize()` does not recognize the tagged tuples that `order_sensitive_keys.py` builds, so it wraps every order-sensitive node in two generic-sequence layers. Half of the tuples in every filter-derived cache key carry no information, yet they stay resident for each entry outside the BSON budget and are rebuilt on every lookup. In the [process-memory report](../../../../reports/process-memory/summary.md#per-entry-attribution), key tuples are the largest bookkeeping cost of small namespace entries.

## What Changes

- Canonical keys represent each order-sensitive mapping, sequence, float, and BSON Int64 node with one tagged tuple whose payload alone is canonicalized.
- Re-canonicalizing a canonical key returns it unchanged without walking or copying it, including order-sensitive subtrees nested inside find and generic `find_one` discriminators.
- Key equality, hashing, numeric subtype and bool/int distinctions, NaN and unhashable rejection, cache outcomes, and find limit compatibility stay as they are. A test-only copy of the current algorithm serves as the oracle for this.
- The shared-cache benchmark wire protocol encodes the new canonical tags.
- The process-memory report, deployment memory guidance, `context7.json` rule, and changelog reflect the new per-entry measurements.
- No public API, configuration, or budget semantics change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cache-core`: Canonical keys must keep one tuple per order-sensitive node, and re-canonicalization must reuse canonical subtrees, without changing which inputs share a key.
- `property-based-testing`: Generated inputs must show that the compact representation keeps the equality classes of the previous representation.

## Impact

- Code: `src/client_query_cache/_core/canonical.py` and `_core/order_sensitive_keys.py`; every namespace key, alias key, compound identity, and non-default read shape gets a smaller representation.
- Benchmark harness: tag registry in `benchmarks/stream_cost/shared_cache/wire.py`.
- Tests: `tests/core/test_canonical.py`, `tests/core/test_order_sensitive_keys.py`, a new test-only legacy oracle, and `tests/shared_cache/test_wire.py`.
- Evidence and documentation: `reports/process-memory/summary.md`, `docs/user/operations/deployment.md`, `context7.json`, and `CHANGELOG.md`.
