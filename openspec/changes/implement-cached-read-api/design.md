## Context

The composed recovery seam, cache core, and change-stream manager provide the prerequisites for user-visible cached reads. The API is deliberately narrower than transparent interception of all PyMongo methods.

## Goals / Non-Goals

**Goals:** Provide equivalent sync/async reads, identity-aware aliases, safe generic result caching, and raw escape hatches.

**Non-Goals:** This change does not cache writes, change sessions, or admit partially consumed cursor data.

## Decisions

- Wrap supplied PyMongo collections; expose raw collections for unsupported operations.
- Detect whether the wrapped collection is backed by a MongoDB view (its data depends on the namespace(s) named in the view's `viewOn`/pipeline, not the view's own namespace) and mark it cache-ineligible if so: bypass cache lookup and admission for every read against it, since writes to its backing namespace(s) never advance the view's own namespace generation and change-stream events for those writes are routed under the backing namespace, not the view's. This is the same conservative treatment as cross-collection aggregation stages below, applied at the collection level instead of per-pipeline. A namespace can become a view either by an existing collection being dropped and recreated, or by coming into existence as a view for the first time; both advance the namespace epoch (`implement-cache-core` advances the epoch on `create` as well as on clear, precisely so a namespace's first appearance is not silently missed). The facade therefore does not check collection type on every read, only the first time it handles a read for a namespace after observing that the namespace epoch has advanced past the one recorded at its last check — this re-verification is rare (only after a drop/rename/clear/create) rather than a per-read cost, and it covers both a wrapper created for an ordinary collection that is later recreated as a view, and a wrapper created before its namespace existed at all. This guarantee is scoped the same way as every other invalidation in this system: it holds once the manager's change-stream worker has processed the `create`/clear event that made the namespace view-backed, not at the instant the DDL runs on the server. A read that races ahead of that event delivery may still observe the prior eligibility determination — this is the same bounded/eventual coherency `implement-change-stream-coherency` already documents for ordinary writes, not a new, weaker promise invented for views.
- Treat `_id` and declared simple/compound unique keys as document aliases. An `_id` read always knows its document identity before issuing the database read, so it captures that identity's identity generation and the namespace epoch up front and admits an identity-guarded entry, keyed by that identity and the read's shape (per `implement-cache-core`) — it does not capture or depend on the namespace generation, so writes to other documents in the same namespace never invalidate it. A unique-key read whose alias is not yet resolved (first lookup by that key value, or after its alias was pruned) cannot know its document identity before the read completes, so it captures only the namespace generation before the read; on no match it admits a negative result guarded by the captured namespace generation alone, since "no document matches this key" is a membership fact about the whole namespace, not about one document's identity. On a match it resolves and records the alias, admits a namespace-guarded entry keyed by the unique-key definition and value plus read shape guarded by the captured namespace generation (as with a negative result), and — in the same namespace-lock critical section as the namespace-generation compare-and-decide, which already establishes that no write has touched this namespace, and therefore this document, since the generation was captured — also reads the document's current identity generation and admits a second, identity-guarded entry for the same document and read shape, guarded by that identity generation and the current namespace epoch. Admitting both is not optional: cache-core's alias-pruning rule keeps an alias alive only while a cached entry still references the identity it resolves to, and a namespace-guarded entry carries no identity reference at all, only a namespace generation — if the first match admitted only the namespace-guarded entry, the alias just published would have nothing referencing its identity and would be pruned immediately, so a later read of the same key value would never actually take the promised identity-guarded path. Admitting the identity-guarded entry at the same time is what gives the alias something to survive on, and it costs no extra database round trip since the document is already in hand from the read that just matched. Because resolving the alias requires the document's canonical identity even when the caller's own projection excludes `_id` (e.g. `{"_id": 0, "name": 1}`), the facade ensures `_id` is present in the server-side projection for an unresolved-alias lookup — but MongoDB projections cannot mix inclusion and exclusion on non-`_id` fields, so the facade cannot simply merge in `_id: 1`: for an inclusion-style projection (`{"_id": 0, "name": 1}`), overriding `_id: 0` to `_id: 1` stays valid, since `_id` is exempt from the mixing rule; for an exclusion-style projection (`{"_id": 0, "secret": 0}` or `{"secret": 0}`), the facade instead omits any `_id: 0` the caller supplied — MongoDB includes `_id` by default in an exclusion-style projection unless it is explicitly excluded, so dropping that exclusion is sufficient and never introduces a mixed inclusion/exclusion projection. The facade strips `_id` from the returned document before handing it to the caller if the caller's own projection excluded it; the cached result (admitted under the caller's original read shape) never includes `_id` unless the caller asked for it. Cache other fully materialized results as namespace-guarded entries behind cache-core's per-collection namespace generation so writes anywhere in that collection conservatively invalidate membership and ordering.
- Force eligible cache-admitted reads to primary plus majority. If the caller selected a secondary or non-majority read profile on the wrapped collection or operation, bypass both cache lookup and admission and preserve the caller's PyMongo read options.
- Admit `find`/aggregate only after complete materialization and capacity validation. Sync and asyncio share behavioral tests but use native driver APIs.
- Reject aggregation pipelines containing a cross-collection stage (`$lookup`, `$unionWith`, `$graphLookup`), a write stage (`$out`, `$merge`), a `$sample` stage, or a nondeterministic or time-dependent expression at any nesting depth (`$rand`, and the system variables `$$NOW` and `$$CLUSTER_TIME`) from caching: admit only pipelines whose result depends solely on reading the wrapped collection and is deterministic given the collection's current contents, guarded by that collection's namespace generation as with any other derived result. A `$lookup`/`$unionWith`/`$graphLookup` pipeline reads a foreign collection that cache-core's per-namespace generation guard has no way to depend on without tracking every namespace a pipeline touches and validating all of them atomically at admission — added complexity this change defers until hit-rate data justifies it. A `$out`/`$merge` pipeline has a database write side effect on every execution; caching its result would skip that side effect on a later hit, which silently breaks the pipeline's own semantics regardless of invalidation correctness. A `$sample` stage, a `$rand` expression, or `$$NOW`/`$$CLUSTER_TIME` can each produce a different result on every execution with no write to the collection at all — `$$NOW`/`$$CLUSTER_TIME` are fixed for the duration of one pipeline run but vary across runs, the same caching hazard as `$rand` through a different mechanism; caching any of them would freeze a nondeterministic or time-dependent query to its first answer indefinitely, which the namespace-generation guard has no way to detect since nothing invalidates it. This list of nondeterministic constructs is not exhaustively enumerable from MongoDB's own documentation; it covers the well-known cases and is expected to grow if others are identified. Bypassing these pipelines (same treatment as partial/tailable/oversize reads) is the conservative default: it never returns stale joined data, skips a write side effect, or freezes a random or time-dependent result, at the cost of caching nothing for these pipeline shapes for now. The same hazard reaches `find`, `count_documents`, and `distinct` through their plain filter document, not only through aggregation pipelines: a filter containing `$where` embeds arbitrary JavaScript that can reference `Math.random()` or the current time, and a filter containing `$expr` embeds the same aggregation-expression syntax a pipeline can, including `$rand`/`$$NOW`/`$$CLUSTER_TIME`. Reject a `find`/`count_documents`/`distinct` read whose filter contains `$where`, or an `$expr` containing one of the same nondeterministic or time-dependent expressions rejected in pipelines, from caching, for the identical reason.
- Wrap `count_documents`/`estimated_document_count`/`distinct` results in a single-field BSON envelope document before admission, so cache-core's existing BSON storage, weight measurement, and encode/decode isolation apply unchanged to non-document values.

## Resource and Complexity Costs

```text
identity read (_id, or unique key with a resolved alias)
  -> hash lookup on (identity, shape) key   O(1) amortized; keyed by canonical
                                             identity plus read shape (e.g.
                                             projection), per `implement-cache-core`,
                                             so a projected read never collides
                                             with a full-document read
  -> generation check                       O(1); identity generation + namespace
                                             epoch, not namespace generation
  -> BSON-decode on hit                     O(document size), CPU + allocation
  -> PyMongo find_one on miss                1 network round trip + server-side lookup

identity read (unique key, unresolved alias or negative result)
  -> namespace generation capture     O(1); no identity generation to capture yet,
                                       since the document identity is unknown
                                       before the read responds
  -> PyMongo find_one, `_id`          1 network round trip + server-side lookup;
     ensured present in the           for an inclusion-style caller projection,
     server-side projection           `_id: 0` is overridden to `_id: 1` (valid,
                                       `_id` is exempt from the mixing rule); for
                                       an exclusion-style caller projection, any
                                       `_id: 0` is instead omitted rather than
                                       overridden, since forcing `_id: 1` into an
                                       exclusion-style projection is rejected by
                                       MongoDB as a mixed inclusion/exclusion
                                       projection, and omission is unnecessary
                                       anyway — exclusion-style projections
                                       already include `_id` by default
  -> alias resolution on match        O(1); records key value -> identity mapping
                                       so subsequent reads of the same key value
                                       use the identity-generation path above
  -> strip `_id` if caller excluded it  O(1); the value returned to the caller,
                                          and the value admitted to the cache,
                                          matches the caller's original requested
                                          shape — the forced `_id` fetch is
                                          invisible to both
  -> admit namespace-guarded entry    O(1); a match or a negative result is
                                       guarded the same way a generic result is,
                                       not by an identity generation, keyed by
                                       (unique-key definition, value, read shape)
  -> admit identity-guarded entry     O(1) additional, on a match only; no extra
     as well (match only)             database round trip, since the document is
                                       already in hand — required so the just-
                                       published alias has an identity-guarded
                                       entry to keep it from being pruned
                                       immediately (see Decisions)

bounded cursor read (find / aggregate)
  -> initial query + getMore round trips   1 round trip to open the cursor, plus
                                            1 round trip per additional batch until
                                            the cursor is exhausted; count scales
                                            with result size / batch size
  -> server-side scan/sort/aggregation     depends on filter selectivity, indexes,
                                            and pipeline stages; not bounded by the
                                            returned result size
  -> data transfer                         O(result size), network I/O
  -> full cursor materialization            O(result size), CPU + allocation,
                                             paid before capacity is known
  -> BSON-encode to determine size       O(result size), CPU + allocation; the
                                          cache-core budget is measured in encoded
                                          BSON bytes, so capacity cannot be checked
                                          without serializing the result (or an
                                          equivalent full traversal) first — this
                                          cost is paid even when the result is then
                                          rejected as oversize
  -> admit if within bounds, else discard   the encoded bytes are reused for
                                             admission; discarding still pays the
                                             materialization and encoding cost above

bounded command read (count_documents / estimated_document_count / distinct)
  -> single command round trip           1 network round trip, no cursor
  -> server-side execution               `count_documents` and `distinct` are not
                                          bounded by the returned payload size in
                                          either case: an unindexed filter scans the
                                          full collection, and an indexed filter
                                          scans or inspects the matching index keys —
                                          cost scales with matching-key cardinality,
                                          not the returned result size, so a
                                          high-cardinality indexed filter still
                                          dominates over a small returned payload.
                                          `estimated_document_count` reads collection
                                          metadata and does not scan documents or
                                          index entries.
  -> client-side result                  O(1) allocation for count results;
                                          `distinct` allocation scales with the
                                          number of distinct values found, which is
                                          not independent of collection size — a
                                          match set with mostly-unique values can
                                          produce a distinct-value list close to
                                          collection scale before capacity validation
                                          ever rejects it
  -> capacity validation + encode        count and estimated-count results are
                                          integers and `distinct` results are lists
                                          of scalar/document values, neither of which
                                          is a BSON document on its own; wrapped in a
                                          single-field envelope document before being
                                          handed to cache-core, so encoding, weight
                                          measurement, and decode isolation reuse the
                                          same path as cursor results
```

## Likely Bottlenecks

Materializing a `find`/aggregate cursor and BSON-encoding it to measure size against the cache-core budget means the CPU, memory, and allocation cost of a large result is paid in full even when the result turns out to be too large to cache and is discarded — there is no cheaper size check available because the budget is defined in encoded BSON bytes. For read-heavy workloads with large or unbounded result sets, this is expected to dominate over the cache-core storage operations themselves. `count_documents` and `estimated_document_count` avoid this because they return a small, near-constant-size command result. `distinct` does not: an unindexed filter over mostly-unique values can produce a distinct-value list that approaches collection scale, carrying both the server-side scan cost and the client-side encode-before-validate cost of the cursor path.

## Open Questions

- Materialization strategy: the Decision above admits `find`/aggregate results only after complete materialization and BSON-encoding (see Resource and Complexity Costs), so an oversized result pays the full materialization and encoding cost before being discarded. An alternative is tracking encoded size incrementally as documents arrive and abandoning cache admission once the running total exceeds the budget, while still streaming the full result to the caller. Not changed in this session; left for a future coding-agent deep dive to evaluate against the correctness/complexity trade-offs of the current approach.

## Risks / Trade-offs

- [Generic result invalidation is broad] → Namespace-generation invalidation favors correctness over hit rate.
- [Materialization uses local memory] → Apply cache-core entry limits and never admit partial or oversize results.
- [A cached aggregation result has no way to depend on a foreign namespace] → Bypass caching entirely for pipelines containing `$lookup`, `$unionWith`, or `$graphLookup` rather than risk returning stale joined data.
- [A cached `$out`/`$merge` result would skip that pipeline's write side effect on a hit] → Bypass caching entirely for pipelines containing `$out` or `$merge`.
- [A view's data depends on a namespace the cache doesn't track] → Detect views and bypass caching for every read against them, rather than risk stale results from writes to the backing collection.
- [A collection wrapped while ordinary could later be dropped and recreated as a view] → Re-verify collection type whenever the namespace epoch has advanced since the last check, rather than trusting a one-time determination made at wrap time forever.
- [View eligibility can only be revoked once the change-stream worker processes the event, not at the instant the DDL runs] → Scope the guarantee to "after event processing," matching the bounded/eventual coherency already documented for ordinary writes, rather than claiming an instantaneous guarantee the architecture can't deliver.
- [A cold or negative unique-key read has no document identity to guard admission with] → Capture and guard with the namespace generation instead until an alias resolves, matching how a generic result is guarded.
- [A canonical-identity-only key could let a projected `_id`/unique-key read collide with a full-document read for the same document] → Key identity-guarded entries by (identity, read shape), matching cache-core's contract, rather than by identity alone.
- [A unique-key read whose caller-supplied projection excludes `_id` has no identity to resolve an alias with] → Ensure `_id` is present in the server-side projection for an unresolved-alias lookup, then strip it from the returned and cached value if the caller's own projection excluded it.
- [Forcing `_id: 1` into an exclusion-style projection would be rejected by MongoDB as a mixed inclusion/exclusion projection] → Override `_id: 0` to `_id: 1` only for an inclusion-style caller projection; for an exclusion-style one, omit the caller's `_id: 0` instead, relying on `_id` being included by default.
- [A cached aggregation result could depend on the wall-clock time it was computed at, via `$$NOW`/`$$CLUSTER_TIME`, with no write to invalidate it] → Bypass caching for pipelines using these system variables, the same conservative treatment as `$rand`/`$sample`.
- [`$where`/`$expr` in a plain `find`/`count_documents`/`distinct` filter can be just as nondeterministic as an aggregation pipeline, but only pipelines were scanned] → Reject filters containing `$where`, or `$expr` embedding the same nondeterministic expressions already rejected in pipelines.
- [A namespace-guarded entry admitted for a first-time unique-key match carries no identity reference, so the alias it publishes would be pruned immediately and never actually deliver the promised identity-guarded path] → Also admit an identity-guarded entry for the same match, using the document already in hand, so the alias has something to survive on.

## Migration Plan

Implement sync identity reads first, add bounded generic reads, then establish asyncio parity and ownership/error tests against independent raw writers.
