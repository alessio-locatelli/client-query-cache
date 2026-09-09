## 1. Implement synchronous cached reads

- [ ] 1.1 Add synchronous collection/database facades with raw-PyMongo fallback, primary/majority routing, session bypass, bypass for caller-selected secondary or non-majority profiles, and view detection that marks a view-backed collection cache-ineligible and re-verifies whenever the namespace epoch has advanced since the last check (covering both clear and `create` events); verify spies observe direct delegation with the original read options, that reads against a view never hit or admit, that a collection dropped and recreated as a view loses eligibility, and that a namespace wrapped while absent and later created as a view is also detected.
- [ ] 1.2 Add `_id` identity caching guarded by identity generation plus namespace epoch and keyed by identity plus read shape, and declared unique-key identity caching that captures only the namespace generation for an unresolved alias or a negative result (keyed by unique-key definition, value, and read shape), forces `_id` into the server-side projection for alias resolution regardless of the caller's own projection and strips it from the returned/cached value if the caller excluded it, and resolves the alias to the identity-guarded path on a match, per `design.md`; verify an independent raw client drives invalidation for both resolved and unresolved cases, that a projected read never collides with a full-document read for the same identity, and that a unique-key match with a projection excluding `_id` still resolves its alias without leaking `_id` to the caller or the cached value.

## 2. Implement bounded generic results

- [ ] 2.1 Add fully materialized bounded `find`, aggregate, count, estimated-count, and distinct caching, using cache-core's per-collection namespace generation and the single-field result envelope from `design.md`; verify membership, ordering, projection, limit, and aggregation invalidation cases.
- [ ] 2.2 Reject partial, tailable, exhaust, oversize, and unsupported cursor results, including aggregation pipelines containing `$lookup`, `$unionWith`, `$graphLookup`, `$out`, `$merge`, `$sample`, or a `$rand` expression at any nesting depth; verify no rejected result is admitted, that an `$out`/`$merge` pipeline's write side effect still executes, and that a `$sample`/`$rand` pipeline returning different results across two executions is never served from the cache.

## 3. Implement asyncio parity

- [ ] 3.1 Add native asyncio facades with the same supported reads and bypass rules; verify parity against PyMongo 4.13 `AsyncMongoClient`, the declared runtime minimum.
- [ ] 3.2 Verify ownership, close, context-manager, error, and caller-value-isolation behavior in both execution models.
