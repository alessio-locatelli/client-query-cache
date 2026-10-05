# Proposal

## Why

Cached `find()` cursors currently require an exact final query discriminator, including the limit. A complete cached result from a larger positive limit or an unlimited query can supply the requested prefix without another MongoDB read when every other cache-relevant input matches.

## What Changes

- Add compatible-result lookup for positive-limit `find()` executions in both synchronous and asyncio APIs.
- Keep different limits as distinct physical query keys; reference resident source entries rather than storing copies for smaller limits.
- Bound candidate lookup to the namespace and query family, with normal source-entry generation checks, LRU access, and one hit or miss recording per lookup.
- Return an isolated requested prefix through the existing native cursor subclasses, using the final chained query shape.
- Preserve exact-key behavior for unlimited and negative-limit requests. Negative-limit entries cannot supply compatible results.
- Keep filter equivalence, other query-shape changes, aggregation subsumption, and general query optimization outside this change. Filter normalization is planned separately in `normalize-find-filter-predicates`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cached-read-api`: Allow a positive-limit find cursor to consume a compatible complete result without changing cursor or admission contracts.
- `cache-core`: Separate physical key identity from result compatibility; maintain a bounded family index and account for compatible hits once.

## Impact

The shared cache core, namespace state, namespace admission/reclamation, cursor capture metadata, and both `cursors.py` implementations are affected. Extend the existing real-server cursor command monitoring and core lifecycle tests, measure lookup and decoding costs, and update `docs/user/usage/cached-reads.md`, affected API references, and `context7.json` during implementation. No new public method, configuration mode, or dependency is required.

The main cache-core scenario currently forbids reuse across any differing query input. Its delta distinguishes physical query identity from explicitly supported reuse. This change is executable on its own: its filter representation stays unchanged, and its feature-specific requirements do not depend on filter normalization.
