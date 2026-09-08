## Context

The prototype contains unbounded cache types. The retained architecture requires a shared manager budget, immutable value storage, and admission guards before facades or streams are introduced.

## Goals / Non-Goals

**Goals:** Establish manager state, canonical identity, BSON-weighted LRU storage, and safe inspection.

**Non-Goals:** This change does not watch MongoDB or expose public cached reads.

## Decisions

- Use one manager-owned weighted BSON LRU with a 64 MiB default and a 1 MiB maximum entry, both configurable.
- Represent document and derived-result identities separately. Namespace generation guards prevent an older in-flight read from being admitted after invalidation by serializing generation advancement with the compare-and-insert admission operation and rejecting entries from older generations during lookup.
- Encode on admission and decode on return to isolate caller values and measure resident size consistently.
- Make lifecycle and measurement snapshots immutable and safe for logs.

## Resource and Complexity Costs

```text
cache admission
  -> BSON-encode value                    O(document size), CPU + allocation
  -> compute entry weight                 O(1), the already-encoded byte length,
                                           not a separate traversal
  -> generation compare-and-insert        O(1) amortized; whether and how this
     (atomic)                             contends with concurrent admissions and
                                           lookups on the same namespace depends on
                                           the synchronization strategy, which is
                                           undecided (see Open Questions)
  -> LRU insert + evict                   O(1) amortized per evicted entry

cache lookup
  -> hash lookup            O(1) amortized
  -> generation check       O(1)
  -> BSON-decode value      O(document size), CPU + allocation

invalidation (single-entry alias removal)
  -> alias table removal        O(k), k = aliases for the invalidated identity
  -> whether removing one identity's aliases also requires bumping the namespace
     generation — and therefore rejects every other entry sharing that
     namespace, not just the invalidated identity — depends on namespace
     granularity, which is undecided (see Open Questions)

invalidation (namespace clear)
  -> generation bump                    O(1), makes existing entries ineligible
                                         for hits immediately
  -> physical entry reclamation         if chosen, requires enumerating the entries
                                         that belong to the cleared namespace; the
                                         Decisions above specify only one shared LRU
                                         with no per-namespace index, so without an
                                         auxiliary index this enumeration is a full
                                         scan of the shared cache, O(N) in total
                                         manager entries, not O(n) in the namespace
                                         being cleared; a per-namespace index would
                                         restore O(n) at the cost of maintaining that
                                         index on every admission and eviction —
                                         neither the reclamation strategy nor the
                                         indexing approach is decided (see Open
                                         Questions)
```

## Likely Bottlenecks

BSON encode/decode CPU on admission and lookup is expected to dominate for documents approaching the 1 MiB max-entry size. Lock contention on the shared LRU and generation state is also expected to matter once concurrent sync-thread and asyncio-task callers admit and look up against the same manager, but the locking granularity that determines how severe this is has not been decided (see Open Questions).

## Open Questions

- Namespace granularity is undecided and is the root of several open questions below: cache-core's spec defines one generation counter per cache namespace and rejects every entry from an older generation, but it does not say whether a namespace is scoped per-collection (so any single-document write would bump the whole collection's generation and reject every other document and generic result cached under it, not just the written document), per-document-identity (narrow, but then generic results need their own separate, coarser mechanism), or a two-tier scheme with fine-grained document namespaces and coarse-grained result namespaces. This same ambiguity is why `implement-cached-read-api` cannot say whether its "database generations" for generic results are the same mechanism as cache-core's namespace generations. Needs a deep dive with a coding agent before implementing invalidation, generic-result caching, or the event router's dispatch granularity — `tasks.md` task 1.2 now gates on this.
- Locking granularity for the shared LRU and generation state is undecided: a single manager-wide lock, a lock per namespace, or a lock-free structure each trade off differently against the dual sync/asyncio facade design. Sync threads and asyncio tasks share one manager, so this must be settled before the manager contracts and LRU storage are implemented. Needs a deep dive with a coding agent before implementation — `tasks.md` tasks 1.1 and 2.1 now gate on this.
- The cache is explicitly process-local, so every application process gets its own budget and its own change-stream cursors (see the corresponding open question in `implement-change-stream-coherency`). The resulting per-process resource multiplication is not yet analyzed here or in capacity documentation.
- Namespace-clear reclamation strategy is undecided: physically removing every affected entry on clear keeps the shared budget accurate immediately, while marking entries generation-invalid and leaving them for the LRU to evict later avoids an immediate scan but lets stale, unusable entries continue occupying the shared budget and degrade hit rate for other namespaces until they age out. Physical reclamation also requires a way to enumerate a namespace's entries — the current Decisions specify one shared LRU with no per-namespace index, so reclamation without one is a full O(N) scan of the shared cache rather than O(n) in the cleared namespace. Both the reclamation strategy and, if physical reclamation is chosen, the indexing approach need a decision before implementing namespace clearing — `tasks.md` task 2.2 now gates on this.

## Risks / Trade-offs

- [BSON serialization adds CPU] → It buys mutation isolation and accurate weighted capacity; benchmarks evaluate the cost later.
- [In-flight reads race with invalidation] → Capture generation before the database read, serialize the generation check and cache insertion with invalidation advancement, and reject older-generation entries during lookup.

## Migration Plan

Replace prototype storage with driver-neutral primitives, cover them with pure unit tests, then expose them only through later facade work.
