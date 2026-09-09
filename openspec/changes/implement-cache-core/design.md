## Context

The prototype contains unbounded cache types. The retained architecture requires a shared manager budget, immutable value storage, and admission guards before facades or streams are introduced.

## Goals / Non-Goals

**Goals:** Establish manager state, canonical identity, BSON-weighted LRU storage, and safe inspection.

**Non-Goals:** This change does not watch MongoDB or expose public cached reads.

## Decisions

- Use one manager-owned weighted BSON LRU with a 64 MiB default and a 1 MiB maximum entry, both configurable.
- Scope one cache namespace to exactly one MongoDB namespace (`<database>.<collection>`), matching the official MongoDB namespace definition. Each namespace maintains two coarse counters and each document identity within it maintains one fine counter:
  - **Namespace generation** — advanced by every write (insert/update/replace/delete) to any document in the collection, and by a namespace clear or namespace creation.
  - **Namespace epoch** — advanced by a namespace clear (drop/rename/dropDatabase, or an explicit application-level clear) and by namespace creation, never by an ordinary write. Creation advances the epoch too because a namespace's identity is defined by more than its name: a namespace that never existed before (no prior drop observed) can still come into existence as a view rather than an ordinary collection, and nothing else would otherwise signal that the collection-type determination a caller made before the namespace existed is now stale.

  Creation advances the namespace generation as well as the epoch: a namespace-guarded entry (e.g. a cached negative unique-key lookup, or an empty `find` result) admitted while the collection did not yet exist is guarded only by the namespace generation, never the epoch, so if creation bumped only the epoch such an entry would survive the collection coming into existence and could return a stale miss. Because a namespace can accumulate cached namespace-guarded entries while it does not yet exist (probing before a first write is a common bootstrapping pattern, not a rare edge case), creation physically reclaims via that namespace's own entry index, the same as a clear — not left to age out — so it does not silently consume shared budget with entries that were invalidated before the namespace ever had real content.
  - **Identity generation** — advanced only by a write to that specific document.

  The manager's LRU is shared across every active namespace, so every physical cache key SHALL include the owning namespace (`<database>.<collection>`) as an outer component — never bare identity or bare query shape alone — otherwise equal `_id` values or equal queries in two different collections would collide and one collection's cached data could be returned for another's read. Cache-core exposes two entry kinds, and the caller (`implement-cached-read-api`) chooses which one to admit a result as — the choice is not implied by the read's surface shape:
  - **Identity-guarded entries** record and are guarded by an identity generation plus the namespace epoch, not the namespace generation, so a write to a different document in the same namespace does not invalidate them. These require a resolved document identity to exist before the database read, and are keyed by (namespace, canonical identity, read shape) — read shape being projection and any other output-affecting option — never by identity alone, since a projected read and a full-document read for the same identity are different results that must not collide, and never without the namespace, since the same identity value can exist in different collections. A resolved unique-key read and an `_id` read for the same namespace, document, and read shape share the same cache entry; a different namespace or shape does not.
  - **Namespace-guarded entries** record and are guarded by the namespace generation alone. These are used for anything without a resolved document identity available before the read. Cache-core does not interpret the key's contents beyond its namespace component, only that the remainder uniquely identifies the read's shape within that namespace; the caller supplies a key of (namespace, ...) that includes every output-affecting input: for an unresolved-alias or negative unique-key lookup, (namespace, unique-key definition, value, read shape); for a `find`/`aggregate`/`count`/`distinct` result, (namespace, operation type, filter/pipeline, projection, sort, limit, skip, collation, the `distinct` field name where applicable, and any other output-affecting option), canonically serialized so two different queries — in the same namespace or different ones — can never collide under the same key. The `distinct` field name is called out explicitly because none of the other listed inputs represent it, and two `distinct` calls differing only in field would otherwise collide despite returning different value lists.

  Identity-guarded and namespace-guarded cache keys are always disjoint (identity vs. value-based), so the two kinds never occupy the same key and the conditional-put comparison below never has to order a namespace-generation integer against an identity-generation-plus-epoch pair — it only ever compares two entries of the same kind. When a previously unresolved unique-key value is resolved, the current read is still admitted as a namespace-guarded entry under the value-key (correctness doesn't depend on removing it), while future reads of that value go through the identity-guarded path and get their own entry under the identity-key; the two representations of the same document coexisting briefly is an accepted, minor inefficiency rather than something this change actively reconciles.

  A namespace clear advances both the namespace generation and the namespace epoch together, so it invalidates every entry regardless of which kind it is, without needing to enumerate or bump individual document identity generations. Every kind prevents an older in-flight read from being admitted after invalidation by serializing generation advancement with the compare-and-insert admission operation and rejecting entries whose recorded generation(s) do not match the current generation(s) during lookup.

- Keep document-identity aliases in a per-namespace map guarded by that namespace's lock, separate from the weighted LRU (aliases are lightweight routing metadata, not cached values, so they are not weighed against the shared budget). An alias key is the triple (declared unique-key definition, canonical value, collation) — never definition-plus-value alone — so two different unique keys sharing the same value (e.g. `email="x"` and `username="x"` on different documents) cannot collide in the same map, and, separately, two reads of the same key value under different collations cannot share a resolution. Collation changes which document a value actually matches (e.g. a case-insensitive collation can match a document a binary/simple collation would not), so it is part of what a value resolves to, not just an output-shape detail like projection — reusing an alias resolved under one collation for a read under a different collation could return a document that does not actually match under that read's own matching semantics. A namespace clear replaces this map with a fresh empty one in the same namespace-lock critical section as the epoch bump — O(1), no enumeration needed — so a stale alias from before the clear can never route a later read to a resolved-identity entry that belongs to a different document created after the clear (e.g. the same `_id` reused with different field values post-recreate). Publishing an alias into the map SHALL happen only after the admission it accompanies has passed its generation compare-and-insert, in the same namespace-lock critical section — never unconditionally on a database match — so a resolution that loses a race to a concurrent write or clear does not leave behind an alias for a value the document no longer has. Prune an alias using the same "no cached entry and no in-flight capture references the identity" rule as identity-generation pruning, so successful resolutions across many distinct key values do not grow the alias map unboundedly independent of the bounded LRU.
- Guard all three counters and the alias map for a namespace with one lock per collection namespace (bounded cardinality — one lock per active collection, not per document); a document's identity generation is always mutated under its owning collection's lock. Guard the shared LRU's structural mutation (insert/evict/touch) with a separate, short-held manager-wide lock, held outside BSON encode/decode. Never hold a namespace lock and the LRU lock at the same time: the generation compare-and-insert (namespace lock) and the LRU insert (LRU lock) are separate, non-nested critical sections.
  - **LRU insert is a conditional put ordered by generation, not an unconditional overwrite**: it replaces the current entry for a key only if no entry currently occupies that key, or the current entry's recorded generation is older than the incoming entry's; otherwise it discards the incoming entry without touching the resident one. This stops an admission that reaches the LRU lock late — after a newer admission for the same key already inserted — from clobbering that newer, valid entry, regardless of which admission started first.
  - Because releasing the namespace lock before acquiring the LRU lock still leaves a window where a clear or write can race between the compare and the physical insert (with no concurrently racing fresher entry to reject it via the rule above), admission re-validates its captured generation(s) against current under the namespace lock immediately after the LRU insert. This re-validation only decides whether a rollback is needed; it does not perform one. The namespace lock is released first, and only then, if the re-check found a mismatch, is the LRU lock separately acquired to perform the rollback — preserving the same non-nesting rule as every other step here, at the cost of a small window where a since-invalidated entry is briefly visible to a concurrent lookup before the rollback removes it (a lookup still rejects it correctly via the same generation check, so this window is a residency delay, not a correctness gap). Publishing the new entry's token into the namespace's index happens in this same namespace-lock critical section, at the moment re-validation confirms no rollback is needed, rather than being deferred to some later step. This bounds the miss window under normal completion to the LRU-insert-to-re-validation gap, the same one already accepted for eviction's index update — but it is not an absolute bound: if the admitting thread or task is killed or cancelled between the LRU insert and this step (a real possibility for an asyncio task cancelled at an await point, or a process crash), the entry is never published to the index at all. This is still not a correctness gap — the entry is correctly rejected at lookup by generation mismatch regardless of index membership — but its physical reclamation then degrades from immediate, index-driven removal to ordinary LRU recency-based eviction, the same fallback already accepted for an index-missed entry, just without the tight timing bound implied by "the same window" framing above.
  - Every rollback and every index-driven removal (eviction's namespace-index update, namespace-clear reclamation) SHALL identify the exact physical entry it intends to remove — e.g. by entry token or object identity, not by cache key — and remove it only if that key still maps to that same entry. This composes with the conditional put above: if a newer entry has since replaced the one being rolled back, the exact-token removal is a no-op and the newer entry is left untouched.
  - When eviction removes an entry, updating that entry's owning namespace's index happens in a follow-up namespace-lock critical section after the LRU lock is released, not nested under it; a namespace clear that runs in the gap sees a momentarily stale index entry for something already evicted, which is a harmless no-op when encountered.

  Fully lock-free structures were considered and deferred pending profiling evidence.

- Physically reclaim a cleared namespace's entries immediately using that namespace's own index of its cache entries, maintained incrementally (subject to the non-nested locking, conditional put, post-insert re-validation, and exact-entry removal above) on admission and eviction, rather than leaving cleared entries for the LRU to age out or scanning the shared cache.
- Prune a document's identity generation once nothing references it — no cached entry for that identity and no in-flight read still holding a captured value for it, tracked with a small in-flight reference count incremented on capture and decremented when that read's admission attempt completes. This bounds identity-generation state by the number of currently cached plus in-flight document identities in a namespace, not by lifetime write history, so a write-heavy, high-cardinality collection cannot grow this metadata unboundedly.
- Encode on admission and decode on return to isolate caller values and measure resident size consistently.
- Make lifecycle and measurement snapshots immutable and safe for logs.

## Resource and Complexity Costs

```text
cache admission
  -> BSON-encode value                    O(document size), CPU + allocation
  -> compute entry weight                 O(1), the already-encoded byte length,
                                           not a separate traversal
  -> generation compare-and-insert        O(1) amortized, held under the target
     (atomic, per-namespace lock)         namespace's lock; compares namespace
                                           generation for namespace-guarded
                                           entries, or identity generation +
                                           namespace epoch for identity-guarded
                                           entries; concurrent admissions against
                                           different namespaces do not contend
                                           this lock
  -> LRU conditional put                  O(1) amortized, held under the short
                                           manager-wide LRU lock as a separate,
                                           non-nested critical section from the
                                           namespace lock above; replaces the
                                           key's current entry only if none
                                           exists or the current one's generation
                                           is older, else discards the incoming
                                           entry without touching the resident one
  -> post-insert re-validation            O(1), held under the namespace lock
     (atomic, per-namespace lock)         again; re-compares the same generation(s)
                                           against current to close the window
                                           between the compare-and-insert decision
                                           and the physical LRU insert; decides
                                           whether to roll back but does not
                                           perform it under this lock
  -> rollback (if re-validation           O(1), namespace lock already released;
     found a mismatch)                    removes this admission's exact entry
                                           token only, never "whatever is currently
                                           under this key" — a concurrent newer
                                           admission for the same key may have
                                           already replaced it
  -> LRU evict (if capacity required)     O(1) amortized per evicted entry, held
                                           under the LRU lock; each evicted
                                           entry's namespace-index update happens
                                           in a follow-up namespace-lock section
                                           after the LRU lock is released

cache lookup
  -> hash lookup            O(1) amortized
  -> generation check       O(1), held under the target namespace's lock; checks
                             namespace generation for namespace-guarded entries,
                             or identity generation + namespace epoch for
                             identity-guarded entries
  -> BSON-decode value      O(document size), CPU + allocation, outside any lock

invalidation (single-entry write)
  -> alias table removal        O(k), k = aliases for the invalidated identity
  -> identity generation bump   O(1); rejects only entries recorded against that
                                 document identity, not other entries sharing the
                                 same namespace
  -> namespace generation bump  O(1); rejects namespace-guarded entries for the
                                 namespace conservatively, on every write,
                                 regardless of which document changed
  -> identity generation +      O(1) each; once no cached entry and no in-flight
     alias prune                capture reference the identity, both its
                                 generation counter and any alias resolving to
                                 it are dropped together

identity-guarded admission with a new alias
  -> alias publish               O(1), held under the same namespace-lock
     (conditional on admission)  critical section as the generation
                                  compare-and-insert; only published if that
                                  compare-and-insert succeeds, so a resolution
                                  racing a concurrent write or clear never
                                  publishes an alias for a document that no
                                  longer matches the key value it was
                                  resolved from

invalidation (namespace clear)
  -> namespace epoch bump               O(1); alone makes every existing entry in
                                         the namespace ineligible for hits and
                                         blocks racing admissions immediately,
                                         identity-guarded or not, since every
                                         entry records the namespace epoch
  -> namespace generation bump          O(1); also advanced so namespace-guarded
                                         entries are rejected by the same check
                                         they already use for ordinary writes
  -> alias map replacement              O(1); the namespace's alias map is
                                         replaced with a fresh empty one under
                                         the same namespace-lock section as the
                                         epoch bump, no enumeration needed
  -> physical entry reclamation         O(n), n = entries belonging to the cleared
                                         namespace, using that namespace's own index
                                         (maintained incrementally, subject to the
                                         non-nested locking above); a budget-freeing
                                         optimization on top of the generation bump,
                                         never a full scan of the shared cache
```

## Likely Bottlenecks

BSON encode/decode CPU on admission and lookup is expected to dominate for documents approaching the 1 MiB max-entry size, since it happens outside any lock and scales with document size regardless of concurrency. The short manager-wide LRU lock (insert/evict/touch) is the remaining shared contention point once multiple concurrent callers — multiple threads sharing one synchronous `CacheManager`, or multiple tasks sharing one asyncio `CacheManager` — admit and look up against the same manager instance; per-namespace locks isolate generation-state contention to callers sharing the same collection, but the LRU lock is still crossed by every admission and eviction regardless of namespace. Whether this LRU lock becomes a measurable bottleneck under concurrent multi-collection load is left to benchmarking rather than assumed here.

## Open Questions

- Cross-facade cache sharing is undecided and out of scope for this change: the recovered prototype's `CacheManager` classes currently only hold a client reference and have no budget, storage, or change-stream cursor yet (those arrive through this change and `implement-change-stream-coherency`). Once implemented per the current per-manager-instance decisions, an application that constructs both a synchronous and an asyncio `CacheManager` for the same MongoDB deployment would end up with two independent manager instances, each with its own budget, storage, and change streams — a write observed through one would not be reflected in the other's cache. Whether that is the intended model, or whether a future change should let both facades share one backend, is not decided here.
- The cache is explicitly process-local, so every application process gets its own budget and its own change-stream cursors (see the corresponding open question in `implement-change-stream-coherency`). The resulting per-process resource multiplication is not yet analyzed here or in capacity documentation.

## Risks / Trade-offs

- [BSON serialization adds CPU] → It buys mutation isolation and accurate weighted capacity; benchmarks evaluate the cost later.
- [A single generation can't both isolate documents and cover namespace clears] → Split the coarse counter in two: a namespace generation bumped by every write (guards derived results, deliberately blind to which document changed) and a namespace epoch bumped only by clears (guards every entry, including point lookups, without needing to enumerate or bump individual document identity generations on clear).
- [In-flight reads race with invalidation, including namespace clears] → Capture generation(s) before the database read, serialize the generation check with invalidation advancement, and reject older-generation entries during lookup.
- [Namespace lock and LRU lock could deadlock if nested] → Never hold both at once; treat generation compare-and-insert and LRU insert/evict as separate, non-nested critical sections, updating an evicted entry's namespace index in a follow-up step after the LRU lock is released.
- [Releasing the namespace lock before the LRU insert leaves a race window] → Re-validate the captured generation(s) under the namespace lock immediately after the LRU insert and roll the insert back on mismatch, so a namespace clear's "immediate reclaim" guarantee holds even against an admission that started just before it.
- [Rollback or reclaim by cache key could delete a legitimate newer entry] → Identify and remove by exact entry token, not by key, so a stale admission's rollback (or a clear's reclamation) can never delete a different, valid entry that has since replaced it under the same key.
- [A late-arriving stale admission could clobber a fresher entry at insert time, before rollback ever runs] → Make the LRU insert itself a conditional put ordered by generation: only replace a key's current entry if none exists or the current one is older, so a late stale insert can never overwrite a newer one regardless of arrival order.
- [A stale alias could survive a namespace clear and route a later read to the wrong document] → Keep aliases in a per-namespace map replaced with a fresh empty one under the same namespace-lock section as the clear's epoch bump.
- [Different unique keys sharing the same value could collide in one alias map] → Key aliases by (unique-key definition, value, collation), never by value alone.
- [A resolution under one collation could be reused for a read under a different collation, whose matching semantics may resolve differently] → Include collation in the alias key, not just definition and value.
- [An alias could be published for a resolution that loses its race to a concurrent write or clear] → Publish an alias only after its accompanying admission's generation compare-and-insert succeeds, in the same lock critical section.
- [The alias map could grow unboundedly independent of the bounded LRU] → Prune an alias with the same "no cached entry, no in-flight capture" rule already used for identity-generation pruning.
- [Comparing generations across entry kinds for the conditional put is ill-defined] → Give identity-guarded and namespace-guarded entries disjoint cache keys (identity-keyed vs. value-keyed) so the comparison only ever happens within one kind.
- [Rollback as specified nested the LRU lock inside the namespace lock] → Split it into two steps: decide under the namespace lock, release it, then perform the removal under the LRU lock separately.
- [A canonical-identity-only key could let a projected read collide with a full-document read for the same identity] → Key identity-guarded entries by (canonical identity, read shape), not identity alone.
- [Namespace creation bumping only the epoch would leave a pre-creation namespace-guarded entry (e.g. a cached negative lookup) valid forever] → Bump the namespace generation on creation too, not only the epoch.
- [Derived-result cache keys were never specified, risking collisions between different queries] → Require the key to canonically encode every output-affecting input (operation type, filter/pipeline, projection, sort, limit, skip, collation); cache-core only requires uniqueness, the caller constructs it.
- [A shared LRU across namespaces means bare identity or query-shape keys could collide across different collections] → Require the namespace to be an outer component of every physical cache key, both identity-guarded and namespace-guarded.
- [Index publication deferred to an unspecified later step could leave an unbounded window for a clear to miss an entry] → Publish the entry's index token in the same namespace-lock critical section as post-insert re-validation success, bounding the miss window to the one already accepted for the insert/re-validation race.
- [The publication step itself can be skipped entirely if the admitting worker is killed or cancelled before reaching it] → Accept this: correctness never depended on index membership (lookup already rejects by generation mismatch), so a missed publication only degrades physical reclamation from immediate to ordinary LRU-eviction timescales, not a correctness regression.
- [Namespace creation was assumed to have nothing to reclaim, but namespace-guarded entries can be cached against an absent namespace] → Physically reclaim on creation via the same per-namespace index used for clears.
- [`distinct` calls differing only in field could collide under a key that omits the field name] → Include the `distinct` field name in the canonical namespace-guarded key.

## Migration Plan

Replace prototype storage with driver-neutral primitives, cover them with pure unit tests, then expose them only through later facade work.
