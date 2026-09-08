## Context

The composed recovery seam, cache core, and change-stream manager provide the prerequisites for user-visible cached reads. The API is deliberately narrower than transparent interception of all PyMongo methods.

## Goals / Non-Goals

**Goals:** Provide equivalent sync/async reads, identity-aware aliases, safe generic result caching, and raw escape hatches.

**Non-Goals:** This change does not cache writes, change sessions, or admit partially consumed cursor data.

## Decisions

- Wrap supplied PyMongo collections; expose raw collections for unsupported operations.
- Treat `_id` and declared simple/compound unique keys as document aliases. Cache other fully materialized results behind database generations so writes conservatively invalidate membership and ordering.
- Force eligible cache-admitted reads to primary plus majority. If the caller selected a secondary or non-majority read profile on the wrapped collection or operation, bypass both cache lookup and admission and preserve the caller's PyMongo read options.
- Admit `find`/aggregate only after complete materialization and capacity validation. Sync and asyncio share behavioral tests but use native driver APIs.

## Resource and Complexity Costs

```text
identity read (_id / unique key)
  -> hash lookup on identity key      O(1) amortized
  -> generation check                 O(1)
  -> BSON-decode on hit               O(document size), CPU + allocation
  -> PyMongo find_one on miss         1 network round trip + server-side lookup

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
                                          is a BSON document that can be encoded the
                                          same way as a cursor result; no envelope or
                                          decode contract for wrapping these values
                                          for cache-core storage is defined yet (see
                                          Open Questions)
```

## Likely Bottlenecks

Materializing a `find`/aggregate cursor and BSON-encoding it to measure size against the cache-core budget means the CPU, memory, and allocation cost of a large result is paid in full even when the result turns out to be too large to cache and is discarded — there is no cheaper size check available because the budget is defined in encoded BSON bytes. For read-heavy workloads with large or unbounded result sets, this is expected to dominate over the cache-core storage operations themselves. `count_documents` and `estimated_document_count` avoid this because they return a small, near-constant-size command result. `distinct` does not: an unindexed filter over mostly-unique values can produce a distinct-value list that approaches collection scale, carrying both the server-side scan cost and the client-side encode-before-validate cost of the cursor path.

## Open Questions

- Generation scope: this design says generic results are invalidated "behind database generations," but cache-core's spec defines one generation counter per cache namespace and its own namespace-granularity decision is itself unresolved (see the corresponding open question in `implement-cache-core`). Until that is resolved, it is unclear whether "database generations" here is the same mechanism as cache-core's namespace generations (in which case the wording should say "namespace generations") or a separate, coarser mechanism the event router does not currently advance. If unresolved before implementation, generic-result entries could stay eligible for stale hits after an invalidating write to a namespace that a coarser database generation would have covered. `tasks.md` task 2.1 (bounded generic-result caching) now gates on this. Needs a deep dive with a coding agent before implementation.
- Result envelope for command reads: `count_documents`/`estimated_document_count` return integers and `distinct` returns a list, neither of which is a BSON document (see Resource and Complexity Costs). No envelope or decode contract for storing and returning these through cache-core is defined yet. Needs a decision before implementing task 2.1.
- Materialization strategy: the Decision above admits `find`/aggregate results only after complete materialization and BSON-encoding (see Resource and Complexity Costs), so an oversized result pays the full materialization and encoding cost before being discarded. An alternative is tracking encoded size incrementally as documents arrive and abandoning cache admission once the running total exceeds the budget, while still streaming the full result to the caller. Not changed in this session; left for a future coding-agent deep dive to evaluate against the correctness/complexity trade-offs of the current approach.

## Risks / Trade-offs

- [Generic result invalidation is broad] → Database-generation invalidation favors correctness over hit rate.
- [Materialization uses local memory] → Apply cache-core entry limits and never admit partial or oversize results.

## Migration Plan

Implement sync identity reads first, add bounded generic reads, then establish asyncio parity and ownership/error tests against independent raw writers.
