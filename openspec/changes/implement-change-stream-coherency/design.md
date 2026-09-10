## Context

The cache-core manager supplies invalidation hooks but no MongoDB source of truth. The prototype watches collections independently; this change consolidates ownership at database scope.

## Goals / Non-Goals

**Goals:** Deliver safe event routing, consolidated watchers, bounded retry, and equivalent sync/async recovery.

**Non-Goals:** This change does not choose which public reads are cacheable or measure benchmark cost.

## Decisions

- Own exactly one database-scoped stream per active cached database. The shared manager owns the cache backend and budget, while each database-scoped supervisor routes events for its database to all of that database's collections; this avoids per-document or per-collection watcher proliferation without leaving other active databases unwatched.
- Require MongoDB server version 6.0 or newer, open the database-scoped stream with `show_expanded_events=True`, and fail closed if the server rejects that option. Project only `_id`, operation type, namespace, document key, rename destination, cluster time, and wall time. Preserve the unmodified resume token and resume with identical options, including the expanded-events option.
- Treat stream health as a continuity state, not a per-write catch-up barrier. A cache hit concurrent with an independent write can be stale until the worker processes that event; after event processing, invalidation is required.
- Handle stream lifecycle explicitly: healthy permits caching; reconnecting bypasses; unresumable loss clears, then reopens. For an invalidate event caused by a drop, rename, or database drop, clear affected namespaces and use [`startAfter` rather than `resumeAfter`](https://www.mongodb.com/docs/manual/reference/operator/aggregation/changeStream/) to open from a safe post-invalidation position. Route `create` events the same way: advance the namespace's epoch (and generation) on creation too, not only on clear, so a namespace coming into existence — including as a view, which nothing else signals — invalidates any collection-type or eligibility determination a caller made before it existed.
- Use capped exponential backoff with jitter and propagate terminal startup failure instead of silently serving cached data.
- Route each database's events through a single serial consumer for this change: it inspects every event in that database, including events for uncached collections, before routing or discarding it. This is the deliberately simple option — per-namespace ordering (required, since generation bumps must apply in event order) comes for free from strict sequential processing, whereas a partitioned or concurrent router would have to reconstruct that guarantee explicitly. Whether heavy irrelevant write traffic on a shared database makes this router a measurable bottleneck is deferred to `benchmark-change-stream-costs`'s consolidated-stream workload, which is built to produce exactly this evidence; see that change's `tasks.md` for the tracked follow-up decision rather than leaving the question open here indefinitely. Resource duplication — one change-stream cursor per active cached database per `CacheManager` instance, and one independent budget per instance, multiplied again by every manager instance and every process caching the same deployment — is an accepted characteristic of the process-local design; see `implement-cache-core`'s design for that decision and `document-public-library`'s tasks for its tracked operator-facing documentation.

## Resource and Complexity Costs

```text
per received change event (insert / update / replace / delete on a single document)
  -> deserialize projected event        O(event size); projected fields are small but
                                         not fixed-size — `documentKey` can carry a
                                         compound shard-key value and namespace/rename
                                         fields are variable-length strings
  -> route to affected namespace(s)     O(1) expected, dispatch keyed by namespace
  -> invalidate namespace generation    O(1)
  -> invalidate aliases for identity    O(k), k = aliases for that identity

bulk invalidation event (collection drop, rename, dropDatabase)
  -> route to affected namespace(s)     O(1), dispatch keyed by namespace/database
  -> clear affected namespace(s)        O(m) namespace-epoch and namespace-generation
                                         bumps, m = number of namespaces affected
                                         (drop/rename), or all of a database's
                                         namespaces for dropDatabase — the epoch bump
                                         is what closes identity-guarded entries
                                         against the clear, the generation bump
                                         closes namespace-guarded entries the same
                                         way an ordinary write does — plus physical
                                         reclamation via each affected namespace's own
                                         entry index — O(n) per namespace, i.e. O(total
                                         entries cached across the affected
                                         namespaces), never a full scan of the
                                         manager's shared cache (see
                                         `implement-cache-core`)
  -> this is bulk work proportional to cached state, not the constant-cost path
     that individual document events take

namespace creation event (create, including view creation)
  -> route to affected namespace         O(1), dispatch keyed by namespace
  -> namespace epoch + generation bump   O(1); invalidates any collection-type
                                         (e.g. view) or eligibility determination
                                         a caller cached from before the namespace
                                         existed
  -> physical entry reclamation          O(n), n = entries cached against the
                                         namespace while it did not yet exist
                                         (e.g. negative unique-key lookups, empty
                                         `find` results — cache-core's namespace
                                         guard admits these for an absent
                                         namespace); treated the same as a clear,
                                         via that namespace's own entry index, not
                                         left to age out — an absent-then-created
                                         namespace is a common bootstrapping
                                         pattern (probe before first write), not a
                                         rare edge case, so skipping reclamation
                                         here would be inconsistent with why
                                         clear already reclaims immediately

per active cached database
  -> exactly one change-stream cursor   one server-side change-stream cursor kept
                                         open via periodic getMore calls; each getMore
                                         checks out a connection from the driver's
                                         pool for the duration of that call rather than
                                         holding a connection reserved for the cursor's
                                         entire lifetime (outside session-pinning cases)
  -> every event in that database is received and inspected, including events
     for uncached collections, before being routed or discarded
```

## Likely Bottlenecks

Per-document-event routing and dispatch is O(1), but deserialization scales with event size (compound `documentKey` values, variable-length namespace/rename fields) and alias invalidation scales with alias count. The single serial consumer per database (see Decisions) must inspect every event in that database, including events for collections that are never cached, before deciding whether to route or discard it — a database with heavy write volume on uncached collections would then make this router a serialization point that can delay invalidation delivery to the cached collections sharing that database. Whether that delay is large enough in practice to warrant partitioning or backpressure is deferred to benchmark evidence (see Decisions and `benchmark-change-stream-costs`'s tracked follow-up task); if a partitioned or concurrent router is chosen as a result, this specific bottleneck no longer applies in the same way. Separately, `dropDatabase` triggers bulk invalidation across every namespace in that database (see Resource and Complexity Costs), so a `dropDatabase` event is expected to be materially more expensive than an ordinary document event and to briefly compete with the router for cache-manager access while it clears every affected namespace; because reclamation is per-namespace-indexed (see `implement-cache-core`), this contention is bounded to the namespaces actually being cleared rather than the manager's entire shared cache, but a `dropDatabase` spanning many large namespaces is still materially more expensive than an ordinary document event.

## Risks / Trade-offs

- [Broader stream sees unrelated writes] → Route and ignore them locally; projection minimizes payload.
- [A write is committed before its event reaches a healthy worker] → Document bounded/eventual coherency and test post-event invalidation rather than promising a per-read write barrier.
- [Resume token is lost] → Clear rather than assert stale entries are safe.
- [A single serial per-database router could become a bottleneck under heavy write traffic on uncached collections, but partitioning would need to reconstruct per-namespace event ordering explicitly] → Ship the single serial consumer for this change; defer the partitioning decision to benchmark evidence tracked in `benchmark-change-stream-costs`.

## Migration Plan

Add deterministic event/router tests first, then replica-set tests with independent writers and controlled cursor failures for each execution model.
