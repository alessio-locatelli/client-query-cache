## Context

The composed recovery seam, cache core, and change-stream manager provide the prerequisites for user-visible cached reads. The API is deliberately narrower than transparent interception of all PyMongo methods.

## Goals / Non-Goals

**Goals:** Provide equivalent sync/async reads, `_id`-based identity caching, safe generic result caching, and raw escape hatches.

**Non-Goals:** This change does not cache writes, change sessions, or admit partially consumed cursor data. It does not cache declared-unique-key reads either: `_id` is the only identity this change treats as an alias-free document identity; unique-key discovery and alias-based identity caching are substantial enough to warrant their own change and are deferred to a follow-up once this facade foundation lands.

## Decisions

- Wrap supplied PyMongo collections; expose raw collections for unsupported operations.
- Detect whether the wrapped collection is backed by a MongoDB view (its data depends on the namespace(s) named in the view's `viewOn`/pipeline, not the view's own namespace) and mark it cache-ineligible if so: bypass cache lookup and admission for every read against it, since writes to its backing namespace(s) never advance the view's own namespace generation and change-stream events for those writes are routed under the backing namespace, not the view's. This is the same conservative treatment as cross-collection aggregation stages below, applied at the collection level instead of per-pipeline. A namespace can become a view either by an existing collection being dropped and recreated, or by coming into existence as a view for the first time; both advance the namespace epoch (`implement-cache-core` advances the epoch on `create` as well as on clear, precisely so a namespace's first appearance is not silently missed). The facade therefore does not check collection type on every read, only the first time it handles a read for a namespace after observing that the namespace epoch has advanced past the one recorded at its last check — this re-verification is rare (only after a drop/rename/clear/create) rather than a per-read cost, and it covers both a wrapper created for an ordinary collection that is later recreated as a view, and a wrapper created before its namespace existed at all. This guarantee is scoped the same way as every other invalidation in this system: it holds once the manager's change-stream worker has processed the `create`/clear event that made the namespace view-backed, not at the instant the DDL runs on the server. A read that races ahead of that event delivery may still observe the prior eligibility determination — this is the same bounded/eventual coherency `implement-change-stream-coherency` already documents for ordinary writes, not a new, weaker promise invented for views.
- Treat `_id` as the only document identity this change caches by. An `_id` read always knows its document identity before issuing the database read, so it captures that identity's identity generation and the namespace epoch up front and admits an identity-guarded entry, keyed by that identity and the read's shape (per `implement-cache-core`) — it does not capture or depend on the namespace generation, so writes to other documents in the same namespace never invalidate it. An `_id` read is always safe to query the database by `_id` directly, because the caller explicitly asked for that identity; whatever that document currently looks like is the correct answer regardless of what else about it may have changed. A cache miss simply queries `find_one({"_id": ...})` with the caller's original projection unchanged — there is no alias to resolve or re-verify, since the query already names the identity directly.
- Cache other fully materialized results (an equality read on any field other than `_id`, plus `find`/aggregate/count/estimated-count/distinct) as namespace-guarded entries behind cache-core's per-collection namespace generation, so writes anywhere in that collection conservatively invalidate membership and ordering. Treating a non-`_id` equality read as a generic namespace-guarded result rather than as an identity alias is deliberate for this change: aliasing a field the caller merely asserts is unique (without verifying it against the database's own index metadata) is a distinct, sizable piece of work — deferred to a follow-up change once this facade foundation is in place — and until then such a read is simply a bounded generic result like any other filtered `find`.
- Force eligible cache-admitted reads to primary plus majority. If the caller selected a secondary or non-majority read profile on the wrapped collection or operation, bypass both cache lookup and admission and preserve the caller's PyMongo read options.
- Admit `find`/aggregate only after complete materialization and capacity validation. Sync and asyncio share behavioral tests but use native driver APIs.
- Reject aggregation pipelines containing a cross-collection stage (`$lookup`, `$unionWith`, `$graphLookup`), a write stage (`$out`, `$merge`), a `$sample` stage, an expression that executes caller-supplied JavaScript (`$function`, `$accumulator`), or a nondeterministic or time-dependent expression at any nesting depth (`$rand`, `$sampleRate`, and the system variables `$$NOW` and `$$CLUSTER_TIME`) from caching: admit only pipelines whose result depends solely on reading the wrapped collection and is deterministic given the collection's current contents, guarded by that collection's namespace generation as with any other derived result. A `$lookup`/`$unionWith`/`$graphLookup` pipeline reads a foreign collection that cache-core's per-namespace generation guard has no way to depend on without tracking every namespace a pipeline touches and validating all of them atomically at admission — added complexity this change defers until hit-rate data justifies it. A `$out`/`$merge` pipeline has a database write side effect on every execution; caching its result would skip that side effect on a later hit, which silently breaks the pipeline's own semantics regardless of invalidation correctness. A `$sample` stage, a `$rand`/`$sampleRate` expression, or `$$NOW`/`$$CLUSTER_TIME` can each produce a different result on every execution with no write to the collection at all — `$sampleRate` is `$rand`-shaped nondeterminism with a different distribution, always embedded via `$expr` (e.g. `{"$match": {"$expr": {"$sampleRate": 0.33}}}`) rather than usable as a bare filter key, matching MongoDB's own documented syntax; `$$NOW`/`$$CLUSTER_TIME` are fixed for the duration of one pipeline run but vary across runs, the same caching hazard as `$rand` through a different mechanism; caching any of them would freeze a nondeterministic or time-dependent query to its first answer indefinitely, which the namespace-generation guard has no way to detect since nothing invalidates it. `$function`/`$accumulator` are rejected unconditionally rather than inspected: they execute an opaque, caller-supplied JavaScript body that could reference `Math.random()`, the current time, or any other nondeterministic or side-effecting construct with no structural marker to detect — unlike `$rand`/`$sampleRate`/`$$NOW`, which are named operators a static scan can find, JavaScript source text can hide the same hazard in a way no reasonable static check can rule out, so rejecting on presence is the only sound option. This list of nondeterministic constructs is not exhaustively enumerable from MongoDB's own documentation; it covers the well-known cases and is expected to grow if others are identified. Bypassing these pipelines (same treatment as partial/tailable/oversize reads) is the conservative default: it never returns stale joined data, skips a write side effect, or freezes a random or time-dependent result, at the cost of caching nothing for these pipeline shapes for now. The same hazard reaches `find`, `count_documents`, and `distinct` through their plain filter document, not only through aggregation pipelines: a filter containing `$where` embeds arbitrary JavaScript, the same unconditional-rejection reasoning as `$function`/`$accumulator` applies, and a filter containing `$expr` embeds the same aggregation-expression syntax a pipeline can, including `$rand`/`$sampleRate`/`$$NOW`/`$$CLUSTER_TIME` — `$expr` is a general query operator, not aggregation-only, so `find({"$expr": {"$sampleRate": 0.33}})` is valid syntax outside a pipeline too. Reject a `find`/`count_documents`/`distinct` read whose filter contains `$where`, or an `$expr` containing one of the same nondeterministic or time-dependent expressions rejected in pipelines, from caching, for the identical reason.
- Wrap `count_documents`/`estimated_document_count`/`distinct` results in a single-field BSON envelope document before admission, so cache-core's existing BSON storage, weight measurement, and encode/decode isolation apply unchanged to non-document values.
- Admit `find`/aggregate results only after complete materialization and BSON-encoding for this change (see Resource and Complexity Costs): an oversized result pays the full materialization and encoding cost before being discarded. This is the deliberately simple option; the alternative — tracking encoded size incrementally as documents arrive and abandoning cache admission once the running total exceeds the budget, while still streaming the full result to the caller — is real but adds meaningful complexity to cache-core's admission contract (currently "encode once, atomically, at a point tied to the pre-read generation capture") for a benefit that only matters for read-heavy workloads with large results. Whether to build it is deferred to `benchmark-change-stream-costs`, which includes a dedicated oversized-result workload (exceeding the max-entry size) to measure exactly this cost; see that change's `tasks.md` for the tracked follow-up task rather than leaving the question open here indefinitely.

## Resource and Complexity Costs

```text
identity read (_id)
  -> hash lookup on (identity, shape) key   O(1) amortized; keyed by canonical
                                             identity plus read shape (e.g.
                                             projection), per `implement-cache-core`,
                                             so a projected read never collides
                                             with a full-document read
  -> generation check                       O(1); identity generation + namespace
                                             epoch, not namespace generation
  -> BSON-decode on hit                     O(document size), CPU + allocation
  -> PyMongo find_one({"_id": ...}) on miss  1 network round trip + server-side
                                             lookup by identity; always safe,
                                             since the caller asked for this
                                             identity directly

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

Materializing a `find`/aggregate cursor and BSON-encoding it to measure size against the cache-core budget means the CPU, memory, and allocation cost of a large result is paid in full even when the result turns out to be too large to cache and is discarded — no check avoids encoding the data at all, since the budget is defined in encoded BSON bytes. What full materialization does forgo is failing fast: encoding and checking size incrementally as the cursor streams, rather than only after every batch has arrived, could abandon an over-budget result without paying for the untouched remainder. Whether that is worth the added admission-contract complexity for this change is deferred to benchmark evidence (see Decisions). For read-heavy workloads with large or unbounded result sets, full materialization's cost is expected to dominate over the cache-core storage operations themselves. `count_documents` and `estimated_document_count` avoid this because they return a small, near-constant-size command result. `distinct` does not: an unindexed filter over mostly-unique values can produce a distinct-value list that approaches collection scale, carrying both the server-side scan cost and the client-side encode-before-validate cost of the cursor path.

## Risks / Trade-offs

- [Generic result invalidation is broad] → Namespace-generation invalidation favors correctness over hit rate.
- [Materialization uses local memory] → Apply cache-core entry limits and never admit partial or oversize results.
- [A cached aggregation result has no way to depend on a foreign namespace] → Bypass caching entirely for pipelines containing `$lookup`, `$unionWith`, or `$graphLookup` rather than risk returning stale joined data.
- [A cached `$out`/`$merge` result would skip that pipeline's write side effect on a hit] → Bypass caching entirely for pipelines containing `$out` or `$merge`.
- [A view's data depends on a namespace the cache doesn't track] → Detect views and bypass caching for every read against them, rather than risk stale results from writes to the backing collection.
- [A collection wrapped while ordinary could later be dropped and recreated as a view] → Re-verify collection type whenever the namespace epoch has advanced since the last check, rather than trusting a one-time determination made at wrap time forever.
- [View eligibility can only be revoked once the change-stream worker processes the event, not at the instant the DDL runs] → Scope the guarantee to "after event processing," matching the bounded/eventual coherency already documented for ordinary writes, rather than claiming an instantaneous guarantee the architecture can't deliver.
- [A canonical-identity-only key could let a projected `_id` read collide with a full-document read for the same document] → Key identity-guarded entries by (identity, read shape), matching cache-core's contract, rather than by identity alone.
- [A cached aggregation result could depend on the wall-clock time it was computed at, via `$$NOW`/`$$CLUSTER_TIME`, with no write to invalidate it] → Bypass caching for pipelines using these system variables, the same conservative treatment as `$rand`/`$sample`.
- [`$sampleRate` (always `$expr`-embedded, per MongoDB's own documented syntax — never a bare filter key or stage) was missing from the nondeterministic-expression list, in both pipelines and plain filters] → Add it alongside `$rand`; the existing `$expr`-scanning mechanism already catches it in both contexts once it's in the list.
- [`$where`/`$expr` in a plain `find`/`count_documents`/`distinct` filter can be just as nondeterministic as an aggregation pipeline, but only pipelines were scanned] → Reject filters containing `$where`, or `$expr` embedding the same nondeterministic expressions already rejected in pipelines.
- [`$function`/`$accumulator` let a pipeline execute opaque, caller-supplied JavaScript that no static scan can prove deterministic] → Reject them unconditionally on presence, the same treatment as `$where`, rather than attempt to analyze the JavaScript body.
- [Full materialization pays the complete cost of pulling and encoding an oversized `find`/aggregate result before rejecting it, but incremental size tracking would add real complexity to cache-core's admission contract] → Ship full materialization for this change; defer the incremental alternative to a benchmark-gated decision tracked in `benchmark-change-stream-costs`.
- [Caching only `_id`-keyed identity reads for this change leaves every other equality read (e.g. a lookup by a unique `email` field) on the lower-hit-rate generic namespace-guarded path] → Accepted for this change; unique-key discovery and alias-based identity caching is deferred to a follow-up change rather than folded into an already-large facade foundation.

## Migration Plan

Implement sync identity reads first, add bounded generic reads, then establish asyncio parity and ownership/error tests against independent raw writers.
