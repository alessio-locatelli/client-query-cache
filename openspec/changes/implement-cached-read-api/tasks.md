## 1. Implement synchronous cached reads

- [ ] 1.1 Add synchronous collection/database facades with raw-PyMongo fallback, primary/majority routing, session bypass, and bypass for caller-selected secondary or non-majority profiles; verify spies observe direct delegation with the original read options.
- [ ] 1.2 Add `_id` and declared unique-key identity caching with external-write eviction; verify an independent raw client drives the invalidation.

## 2. Implement bounded generic results

- [ ] 2.1 Resolve the generation-scope and result-envelope open questions in `design.md`, then add fully materialized bounded `find`, aggregate, count, estimated-count, and distinct caching; verify membership, ordering, projection, limit, and aggregation invalidation cases.
- [ ] 2.2 Reject partial, tailable, exhaust, oversize, and unsupported cursor results; verify no rejected result is admitted.

## 3. Implement asyncio parity

- [ ] 3.1 Add native asyncio facades with the same supported reads and bypass rules; verify parity against PyMongo 4.13 `AsyncMongoClient`, the declared runtime minimum.
- [ ] 3.2 Verify ownership, close, context-manager, error, and caller-value-isolation behavior in both execution models.
