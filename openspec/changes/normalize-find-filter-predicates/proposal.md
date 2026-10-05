# Proposal

## Why

The current find discriminator preserves all mapping order, including top-level predicate order. A small, proven set of semantically equivalent filters can share one resident result instead of causing redundant database reads and storage.

## What Changes

- Introduce a shared find-filter normalization boundary without changing generic canonicalization or order-sensitive BSON representation.
- Support one initial rule: reorder ordinary top-level scalar equality predicates while preserving existing key type distinctions.
- Decline filters containing document or array values, operators, regexes, expressions, custom forms, or other unsupported inputs; retain their existing order-sensitive keys and eligibility.
- Normalize cache identity only; pass the caller's original filter unchanged to native execution and validation.
- Require raw-server differential evidence on the existing supported MongoDB fixture, including matching documents, explicitly sorted ordering, relevant errors, and embedded-document-order fallback counterexamples. Add selected version checks only for a concrete compatibility concern.
- Apply the same filter representation to synchronous and asyncio find lookup and admission, retaining all other read-shape and namespace distinctions.
- Exclude other read methods and additional equivalence rules from this first change. Limit subsumption is planned separately in `add-find-limit-subsumption`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cached-read-api`: Share find results for the explicitly supported filter-equivalence rule while preserving native execution and fallback behavior.
- `cache-core`: Permit proven equivalent filter representations to share identity while retaining all other output-affecting inputs.

## Impact

Add a small filter-key helper under `_core` and integrate it into both find cursor preparation paths. Keep `canonical.py`, `order_sensitive_keys.py`, single-document optimizations, counts, distinct, and aggregation semantics unchanged. Extend core property tests and real-server cursor command monitoring using the existing disposable MongoDB fixture. No test-runner option, version inventory, or new test infrastructure is required. Update the public cached-read guide, affected API references, and `context7.json` during implementation.

This change is executable on its own and modifies only the find filter component. The shared cache-core requirement uses operation-neutral wording; normalization-specific scenarios live in their own added requirement, so no deferred delta reconciliation is required.
