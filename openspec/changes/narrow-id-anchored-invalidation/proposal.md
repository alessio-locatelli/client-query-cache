# Proposal

## Why

Any write to a collection invalidates every namespace-guarded result cached for it. Under steady write churn, namespace-guarded reads almost never hit, and each miss costs more than a direct PyMongo read. A common owner-filtered read, `find_one({"_id": id, "owner": user})`, depends on one document only, yet it is invalidated as broadly as a collection scan. The measurements and the evaluation of broader alternatives are in [design.md](design.md).

The correctness of this narrowing relies on identity routing following MongoDB numeric equality, which the `match-numeric-identities` change established.

## What Changes

- `find_one` filters that pin `_id` to an exact value use the existing per-document identity guard, even with additional predicates, when the effective collation is simple. Writes to other documents no longer invalidate these entries. The additional predicates stay part of the cache key and the executed query.
- Every other namespace-guarded read keeps collection-wide invalidation. This covers `find`, `aggregate`, `count_documents`, `distinct` and `estimated_document_count`, `find_one` without an exact `_id` value, and anchored reads under a non-simple collation.
- A committed research benchmark and development report record the workloads that improve and the ones that do not. Stream-assisted invalidation for equality-filtered reads and the find-miss overhead are deferred to follow-up issues.
- The public API is unchanged.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cached-read-api`: `_id`-anchored compound `find_one` reads move from namespace guards to identity guards.

## Impact

- Code: `src/client_query_cache/_core/identity_reads.py` and `_core/find_one_reads.py`, plus `find_one` routing in both `synchronous/collection.py` and `asynchronous/collection.py`. The change-stream pipeline, `CacheCore` and the stream routing are unchanged.
- Tests: core unit and property tests, and sync and asyncio facade integration tests.
- Evidence: a new `research/invalidation_scope/` benchmark script and a `docs/development/research/` report.
- Docs: the single-document read and fit-assessment sections of the user guides, `docs/development/architecture.md`, `context7.json` and `CHANGELOG.md`.
- Coordination: `benchmark-concurrent-worker-workload` (issue #197) owns the multi-worker evidence for `_id` reads, and this change does not touch its harness.
