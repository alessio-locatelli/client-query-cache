## 1. Implement synchronous cached reads

- [x] 1.1 Add synchronous collection/database facades with raw-PyMongo fallback, primary/majority routing, session bypass, bypass for caller-selected secondary or non-majority profiles, and view detection that marks a view-backed collection cache-ineligible and re-verifies whenever the namespace epoch has advanced since the last check (covering both clear and `create` events); verify spies observe direct delegation with the original read options, that reads against a view never hit or admit, that a collection dropped and recreated as a view loses eligibility, and that a namespace wrapped while absent and later created as a view is also detected.
- [x] 1.2 Add `_id` identity caching guarded by identity generation plus namespace epoch and keyed by identity plus read shape (always safe to query by identity directly, since the caller asked for that identity), with a cache miss querying `find_one({"_id": ...})` using the caller's original projection unchanged, per `design.md`; verify an independent raw client drives invalidation, and that a projected read never collides with a full-document read for the same identity.

## 2. Implement bounded generic results

- [x] 2.1 Add fully materialized bounded `find`, aggregate, count, estimated-count, and distinct caching, using cache-core's per-collection namespace generation and the single-field result envelope from `design.md`; verify membership, ordering, projection, limit, and aggregation invalidation cases.
- [x] 2.2 Reject partial, tailable, exhaust, oversize, and unsupported cursor results, including aggregation pipelines containing `$lookup`, `$unionWith`, `$graphLookup`, `$out`, `$merge`, `$sample`, `$function`, `$accumulator`, or a `$rand`/`$sampleRate`/`$$NOW`/`$$CLUSTER_TIME` expression at any nesting depth, and `find`/`count_documents`/`distinct` reads whose filter contains `$where` or an `$expr` embedding the same expressions; verify no rejected result is admitted, that an `$out`/`$merge` pipeline's write side effect still executes, that a `$function`/`$accumulator` pipeline is rejected regardless of what its JavaScript body does (no attempt to analyze it), and that a `$sample`/`$rand`/`$sampleRate`/`$$NOW`/`$$CLUSTER_TIME`/`$where`/`$expr` read returning different results across two executions is never served from the cache.

## 3. Implement asyncio parity

- [x] 3.1 Add native asyncio facades with the same supported reads and bypass rules; verify parity against PyMongo 4.13 `AsyncMongoClient`, the declared runtime minimum.
- [x] 3.2 Verify ownership, close, context-manager, error, and caller-value-isolation behavior in both execution models.
