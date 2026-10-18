# Design

## Context

See proposal.md for motivation and specs/shared-worker-cache/spec.md for behavior. The owner already handles namespace captures for internal find adapters; the public wrappers currently disable them.

## Decisions

Keep the existing identity fast path. Enable the native cursor subclasses and use owner namespace selection for scalar and command-cursor reads. Reuse the existing query classification, key encoding, majority-read handles, CursorCapture and generation-fenced admissions. Unique-key filters use namespace caching without requiring identity alias discovery: collection-wide invalidation is conservative and preserves their eligible behavior.

Compared with worker-local caches, namespace selection adds IPC on misses and when local selection is unavailable, while enabling first-read reuse across processes. Compared with extending native identity alias publication, namespace selection avoids changing the established identity path and safely handles result membership. Alias publication would reduce invalidations but needs additional index synchronization machinery; no such research is necessary for the requested functional coverage. Existing portable-codec and simple-collation restrictions remain enforced because the shared key and metadata contracts have not been extended.

Centralize shared request preparation and sync/async execution, rather than reproducing classification rules. Keep native cursor batching and immutable capture snapshots instead of eagerly materializing misses: eager materialization violates lazy execution and increases memory for abandoned cursors.

Capture handles include the owner incarnation and a monotonic sequence. Numeric sequences alone can collide after restart and let an unfinished read publish under another query; embedding the incarnation fences both admission and discard without changing the established local identity tokens. A worker-side reconnect check would leave a race between checking and sending; owner validation is authoritative. No additional research is needed beyond the restart-interleaving regression test.

Cache each collection view's immutable codec identity once and reuse it in read shapes. Recomputing it for every scalar or cursor read allocates redundant tuples and registry wrappers; PyMongo changes codec options by creating another collection handle, which receives another cached view. No invalidation mechanism is needed for this immutable input.

## Risks / Trade-offs

- Namespace IPC and BSON snapshots add cold-miss cost; measure separately from hot benefits using existing harnesses.
- A capture crossing an invalidation, expired lease or owner restart must be rejected by the owner; exercise these transitions with real streams.
- Native miss resources outlive manager attachment; closing the manager must not invalidate an already-owned cursor snapshot.

## Migration Plan

No application migration. Reverting the extension restores PyMongo fallback for broader reads without changing ownership or configuration.
