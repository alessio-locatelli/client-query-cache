## Context

The cache-core manager supplies invalidation hooks but no MongoDB source of truth. The prototype watches collections independently; this change consolidates ownership at database scope.

## Goals / Non-Goals

**Goals:** Deliver safe event routing, consolidated watchers, bounded retry, and equivalent sync/async recovery.

**Non-Goals:** This change does not choose which public reads are cacheable or measure benchmark cost.

## Decisions

- Own one database-scoped stream per manager to avoid per-document or per-collection watcher proliferation.
- Project only `_id`, operation type, namespace, document key, rename destination, cluster time, and wall time. Preserve the unmodified resume token and resume with identical options.
- Handle stream lifecycle explicitly: healthy permits caching; reconnecting bypasses; unresumable loss clears, then reopens.
- Use capped exponential backoff with jitter and propagate terminal startup failure instead of silently serving cached data.

## Risks / Trade-offs

- [Broader stream sees unrelated writes] → Route and ignore them locally; projection minimizes payload.
- [Resume token is lost] → Clear rather than assert stale entries are safe.

## Migration Plan

Add deterministic event/router tests first, then replica-set tests with independent writers and controlled cursor failures for each execution model.
