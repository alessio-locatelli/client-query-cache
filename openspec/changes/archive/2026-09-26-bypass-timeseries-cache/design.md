# Design

## Context

See [proposal.md](proposal.md) for motivation. The shared metadata interpreter in `src/mongo_client_cache/_core/collection_metadata.py` stores only `is_view`; both managers return `not cached.is_view` from `ensure_cache_eligible`. All six facade read methods use that gate before cache lookup. Metadata is memoized against the namespace epoch, and absent names currently produce a conclusive non-view result.

MongoDB identifies time-series collections with [`type: timeseries`](https://www.mongodb.com/docs/manual/reference/command/listcollections/) and [does not support change streams for time-series collections](https://www.mongodb.com/docs/manual/changestreams/). The existing view tests in `tests/synchronous/test_collection.py` and `tests/asynchronous/test_collection.py` cover direct fallback, drop/recreation, absent-name creation, and failed metadata probes; they provide the relevant regression structure.

## Goals / Non-Goals

**Goals:** Centralize collection-type eligibility in the shared metadata model, retain sync/async parity, and close the absent-name path without assuming delivery of time-series events.

**Non-Goals:** Implement time-series invalidation, inspect backing bucket collections, add TTLs or polling workers, redesign stream recovery, or complete the broader documentation change. A confirmed ordinary collection remains subject to all existing eligibility restrictions.

## Decisions

### Represent positive eligibility rather than only view status

Replace the view-only metadata flag with a collection-type eligibility representation used by both managers. Only a confirmed `type: collection` qualifies; `view` and `timeseries` are conclusive ineligible results. Missing or unrecognized type information is inconclusive and uses the existing retry-on-next-read behavior. Retain default collation metadata for ordinary collections.

Adding independent time-series checks in all twelve read implementations would duplicate policy and risk missing a method. Merely changing the meaning of `is_view` would obscure the distinction between views and time-series collections. The shared gate already provides direct fallback, option preservation, and bypass accounting, so those paths should be reused.

### Do not cache reads of an absent namespace

Represent an absent `listCollections` result as no eligibility determination and bypass without memoizing it. This also handles a collection created between the probe and the direct read: that read is still not admitted. Recheck on the next eligible-looking read. Negative document results in a confirmed existing ordinary collection remain cacheable.

Keeping the current absent-name admission would depend on a future creation event to revoke eligibility. Since this fix exists because time-series events are unsupported, that dependency cannot establish safety. Rechecking every ordinary collection on every read would add a metadata round trip to cache hits and is unnecessary; retain epoch-based memoization for confirmed types.

### Preserve the existing DDL consistency boundary

For ordinary-to-time-series replacement, rely on processing the ordinary collection's drop event to invalidate entries and metadata, not on time-series creation or writes. Reads racing ahead of that event retain the existing eventual consistency boundary. An absent result observed between drop and recreation must not become a lasting eligibility decision.

Conclusive ineligible metadata can remain memoized until its epoch changes. If time-series-to-ordinary replacement emits no usable event for the logical namespace, conservative continued bypass is acceptable: this change promises safe reads, not automatic restoration of caching in that case. A new manager re-probes. Document this limitation without inventing a new event source.

### Verify the shared boundary with real database behavior

Use parametrized coverage for the six read methods in each execution model against the existing disposable MongoDB replica-set fixture. Check that repeated reads reach PyMongo, successful reads increment bypasses without increasing hits or entries, caller options survive, and server errors propagate. An independent client's acknowledged measurement insert must change applicable query/count results without waiting for an invalidation event. Use valid time-series operations; do not assume all raw operations are accepted by MongoDB.

Cover first access, absent-to-time-series, ordinary-to-time-series after processed drop, and absent-to-ordinary recovery. Keep ordinary positive/negative caching and view/probe-failure behavior covered. Add focused shared metadata cases for ordinary, view, time-series, absent, and inconclusive results. Use fixture-owned setup/cleanup and Faker values, and follow the whole-file test convention review required by AGENTS.md.

## Resource Costs

Confirmed ordinary collection hits retain one local metadata lookup and the existing cache lookup; no new database round trip is intended. First access or stale metadata uses the existing `listCollections` probe. Absent/inconclusive names require a metadata probe plus a direct read per call; time-series reads use direct database I/O after their type is known. Classification and metadata storage remain constant-sized per namespace. Stream ownership and budgets do not change.

Measure ordinary collection hit cost before and after implementation using the retained performance-guard workload and record comparable results with the implementation. Also record metadata-call counts for repeated ordinary, time-series, and absent reads. No performance improvement is claimed by this proposal.

## Risks / Trade-offs

- Repeated absent-name reads cost more database I/O → Accept that cost to avoid caching a result without a safe invalidation source; document the distinction from a missing document in an existing collection.
- Type-probe failures could accidentally become permanent → Preserve visible warning logs and retry on later reads without storing inconclusive metadata.
- Integration tests could pass only because streams failed to start → Establish healthy database availability before testing the collection-type bypass.
- DDL delivery is asynchronous → Synchronize replacement tests on processed ordinary drop, rather than arbitrary sleeps or nonexistent time-series notifications.

## Migration Plan

No public signature or data migration is needed. Apply the change to newly created managers during deployment so process-local state is rebuilt. Update the README with current time-series and absent-namespace bypass behavior. Keep `document-public-library` pending until this prerequisite is implemented and reviewed. If a deployment must revert the fix, use raw PyMongo reads for time-series collections rather than restoring their unsafe cache use.
