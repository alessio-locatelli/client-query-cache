## Context

The cache-core manager supplies invalidation hooks but no MongoDB source of truth. The prototype watches collections independently; this change consolidates ownership at database scope.

## Goals / Non-Goals

**Goals:** Deliver safe event routing, consolidated watchers, bounded retry, and equivalent sync/async recovery.

**Non-Goals:** This change does not choose which public reads are cacheable or measure benchmark cost.

## Decisions

- Own one database-scoped stream per manager to avoid per-document or per-collection watcher proliferation.
- Require MongoDB server version 6.0 or newer, open the database-scoped stream with `show_expanded_events=True`, and fail closed if the server rejects that option. Project only `_id`, operation type, namespace, document key, rename destination, cluster time, and wall time. Preserve the unmodified resume token and resume with identical options, including the expanded-events option.
- Treat stream health as a continuity state, not a per-write catch-up barrier. A cache hit concurrent with an independent write can be stale until the worker processes that event; after event processing, invalidation is required.
- Handle stream lifecycle explicitly: healthy permits caching; reconnecting bypasses; unresumable loss clears, then reopens. For an invalidate event caused by a drop, rename, or database drop, clear affected namespaces and use [`startAfter` rather than `resumeAfter`](https://www.mongodb.com/docs/manual/reference/operator/aggregation/changeStream/) to open from a safe post-invalidation position.
- Use capped exponential backoff with jitter and propagate terminal startup failure instead of silently serving cached data.

## Risks / Trade-offs

- [Broader stream sees unrelated writes] → Route and ignore them locally; projection minimizes payload.
- [A write is committed before its event reaches a healthy worker] → Document bounded/eventual coherency and test post-event invalidation rather than promising a per-read write barrier.
- [Resume token is lost] → Clear rather than assert stale entries are safe.

## Migration Plan

Add deterministic event/router tests first, then replica-set tests with independent writers and controlled cursor failures for each execution model.
