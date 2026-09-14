## Context

`implement-cached-read-api` establishes the synchronous and asynchronous collection facades, view detection, bypass rules, and `_id`-only identity caching. This change extends that same capability to cache reads by a caller's own unique fields (e.g. `email`), without requiring the caller to declare which fields are unique.

## Goals / Non-Goals

**Goals:** Discover unique keys from the server's own index metadata; cache reads by a discovered key as identity-guarded, alias-based entries; keep a resolved alias honest against writes and namespace recreation.

**Non-Goals:** This change does not verify a _caller-declared_ unique key (there is no such declaration API).

## Decisions

- Discover unique keys automatically from the server's own index metadata: on the first read against a namespace whose filter is not an `_id` lookup, and again whenever that namespace's index generation has advanced since the last check (see below), the facade calls `list_indexes()` and keeps only indexes that unconditionally guarantee uniqueness for every document: `unique: true`, no `partialFilterExpression` (a partial index's guarantee only holds for documents matching the partial filter, and deciding whether an arbitrary caller filter is subsumed by that filter is not attempted), not `sparse` (a sparse index's guarantee excludes documents missing the field entirely), and not a hashed key (a unique hashed index guarantees no two documents share a _hash_, which does not soundly imply the original field values are unique).
- Track a per-namespace index generation, separate from cache-core's namespace generation/epoch, incremented whenever the manager's change stream (already opened with `show_expanded_events=True`, per `implement-change-stream-coherency`) delivers a `createIndexes` or `dropIndexes` event for that namespace, and also whenever the namespace epoch itself advances (drop/recreate/create, the same trigger view detection uses, since those also invalidate index metadata wholesale). Discovery re-verifies against this index generation, not against the document-cache namespace generation/epoch directly: an index change has no bearing on which documents are cached or their identities, so routing it through the namespace epoch instead would spuriously reclaim every cached entry for the namespace on an unrelated metadata change.
- A discovered key's field set is taken from the index's own `key` document, in that document's field order, and its collation is the index's declared collation (or the collection's default collation if the index has none). A read only takes the alias path through a discovered key when the read's own effective collation (its explicit `collation` argument, or the collection's default) is exactly the same collation as the index; a coarser-grained index (e.g. case-insensitive) would still soundly cover a stricter-comparison read, but exploiting that requires reasoning about collation strength ordering this change does not attempt, so it is treated as a non-match and the read falls back to the generic bounded-read path instead of losing correctness.
- Discovered unique keys are shared across every facade handle for the same namespace (indexed by namespace in a per-`CacheManager` metadata cache, not per `CachedCollection` instance), so two handles obtained from the same manager always see the same set. `_id` is never discovered this way; it is handled entirely by `implement-cached-read-api` since MongoDB enforces its uniqueness unconditionally without any index to inspect.
- An index change is detected once the manager's change-stream worker has processed the corresponding `createIndexes`/`dropIndexes` event, not at the instant the DDL runs on the server — the same bounded/eventual coherency `implement-change-stream-coherency` already documents for ordinary writes, not a new, weaker promise invented for index metadata.
- A unique-key read whose alias is not yet resolved (first lookup by that key value, or after its alias was pruned) cannot know its document identity before the read completes, because the caller asked for "the document matching `field = value`," not for a specific identity — an alias is only ever the library's own memo of which identity that predicate matched last time, not a substitute for the predicate itself. It therefore captures only the namespace generation before the read and queries by the caller's original predicate (`{field: value}`); on no match it admits a negative result guarded by the captured namespace generation alone, since "no document matches this key" is a membership fact about the whole namespace, not about one document's identity. On a match it resolves and records the alias, admits a namespace-guarded entry keyed by the unique-key definition and value plus read shape guarded by the captured namespace generation (as with a negative result), and — in the same namespace-lock critical section as the namespace-generation compare-and-decide, which already establishes that no write has touched this namespace, and therefore this document, since the generation was captured — also reads the document's current identity generation and admits a second, identity-guarded entry for the same document and read shape, guarded by that identity generation and the current namespace epoch. Admitting both is not optional: cache-core's alias-pruning rule keeps an alias alive only while a cached entry still references the identity it resolves to, and a namespace-guarded entry carries no identity reference at all, only a namespace generation — if the first match admitted only the namespace-guarded entry, the alias just published would have nothing referencing its identity and would be pruned immediately, so a later read of the same key value would never actually take the promised identity-guarded path. Admitting the identity-guarded entry at the same time is what gives the alias something to survive on, and it costs no extra database round trip since the document is already in hand from the read that just matched.
- A read of a key value with an already-resolved alias first checks for a valid identity-guarded cache entry keyed by (resolved identity, read shape); a hit needs no database round trip and is safe, because the cached value was itself admitted only after the query it came from matched the caller's predicate, and it remains guarded by identity generation and namespace epoch against any later write to that document. On a cache **miss**, the facade SHALL still query by the caller's original predicate (`{field: value}`), never by the resolved identity alone — a write to the resolved document could have changed the very field the key was resolved from, and separately, if the namespace was dropped and recreated the same `_id` value could now belong to an entirely different document; querying by identity alone in either case would silently return that document as if it still matched the key, rather than correctly finding no match or a different match. The facade compares the response's identity (or its absence) against the alias's recorded identity: if they agree, the alias was accurate — capture the document's current identity generation and admit/refresh the identity-guarded entry as usual. If they disagree (a different identity matched, or none did), the alias was stale: discard or re-publish it to the new mapping, and admit the result the same way an unresolved-path read would (namespace-guarded if negative, or resolved afresh to the new identity if a different document matched).
- Because resolving an alias requires the document's canonical identity even when the caller's own projection excludes `_id` (e.g. `{"_id": 0, "name": 1}`), the facade ensures `_id` is present in the server-side projection whenever a query might need to resolve or re-verify an alias (an unresolved lookup, or a resolved-alias cache miss) — but MongoDB projections cannot mix inclusion and exclusion on non-`_id` fields, so the facade cannot simply merge in `_id: 1`: for an inclusion-style projection (`{"_id": 0, "name": 1}`), overriding `_id: 0` to `_id: 1` stays valid, since `_id` is exempt from the mixing rule; for an exclusion-style projection (`{"_id": 0, "secret": 0}` or `{"secret": 0}`), the facade instead omits any `_id: 0` the caller supplied — MongoDB includes `_id` by default in an exclusion-style projection unless it is explicitly excluded, so dropping that exclusion is sufficient and never introduces a mixed inclusion/exclusion projection. The facade strips `_id` from the returned document before handing it to the caller if the caller's own projection excluded it; the cached result (admitted under the caller's original read shape) never includes `_id` unless the caller asked for it.

## Resource and Complexity Costs

```text
metadata discovery (unique keys)
  -> list_indexes()                   1 network round trip; only on the first
                                       non-`_id` read for a namespace, or again
                                       after its index generation advances
  -> filter + extract                 O(index count); excludes partial, sparse,
                                       and hashed indexes

identity read (unique key with a resolved alias)
  -> hash lookup on (identity, shape) key   O(1) amortized; same cache-side
                                             lookup as an `_id` read, using the
                                             identity the alias resolved to
  -> generation check                       O(1); identity generation + namespace
                                             epoch, not namespace generation
  -> BSON-decode on hit                     O(document size), CPU + allocation;
                                             no database round trip, and safe
  -> PyMongo find_one({field: value}), `_id` 1 network round trip on miss, by
     on miss, by the ORIGINAL predicate,    the ORIGINAL predicate, never by the
     never by the resolved identity alone   resolved identity alone
  -> compare response identity              O(1); confirms or refreshes the
     against the alias's recorded one       alias, or discards/re-resolves it

identity read (unique key, unresolved alias or negative result)
  -> namespace generation capture     O(1); no identity generation to capture yet
  -> PyMongo find_one, `_id` ensured   1 network round trip; `_id: 0` overridden
     present in the server-side       to `_id: 1` for an inclusion-style
     projection                       projection, or omitted for an
                                       exclusion-style one
  -> alias resolution on match        O(1); records key value -> identity mapping
  -> strip `_id` if caller excluded it  O(1)
  -> admit namespace-guarded entry    O(1); match or negative result
  -> admit identity-guarded entry     O(1) additional, on a match only; no extra
     as well (match only)             database round trip
```

## Risks / Trade-offs

- [A cold or negative unique-key read has no document identity to guard admission with] → Capture and guard with the namespace generation instead until an alias resolves, matching how a generic result is guarded.
- [A unique-key read whose caller-supplied projection excludes `_id` has no identity to resolve an alias with] → Ensure `_id` is present in the server-side projection for an unresolved-alias lookup, then strip it from the returned and cached value if the caller's own projection excluded it.
- [Forcing `_id: 1` into an exclusion-style projection would be rejected by MongoDB as a mixed inclusion/exclusion projection] → Override `_id: 0` to `_id: 1` only for an inclusion-style caller projection; for an exclusion-style one, omit the caller's `_id: 0` instead, relying on `_id` being included by default.
- [A namespace-guarded entry admitted for a first-time unique-key match carries no identity reference, so the alias it publishes would be pruned immediately and never actually deliver the promised identity-guarded path] → Also admit an identity-guarded entry for the same match, using the document already in hand, so the alias has something to survive on.
- [Querying by a resolved alias's identity alone on a cache miss can return a document that no longer matches the key it was resolved from — after a write to that field, or a drop/recreate reusing the same `_id` for a different document] → A resolved-alias cache miss always queries by the caller's original predicate, never by identity alone, and treats a response whose identity disagrees with the alias as evidence the alias is stale.
- [A partial or sparse unique index's guarantee is conditional, and a hashed unique index's guarantee is on the hash rather than the original value] → Exclude all three from discovery rather than reason about partial-filter subsumption or hash-collision soundness.
- [A discovered index's collation may be coarser than a read's effective collation, in which case the index's guarantee would still soundly apply] → Require an exact collation match rather than reason about collation strength ordering; a read that doesn't match falls back to the generic bounded-read path instead of risking an unsound alias.
- [An earlier draft of this design assumed MongoDB change streams never report index lifecycle changes at all; in fact, with `show_expanded_events=True` — which this project's change-stream worker already requires — a `createIndexes` or `dropIndexes` event is delivered for index changes on a live collection. Relying on the assumed absence of these events would have left a dropped unique index usable for aliasing indefinitely] → Route `createIndexes`/`dropIndexes` events to a dedicated per-namespace index generation and re-verify discovery against it, rather than only on namespace-epoch-advancing events; this is genuinely event-driven, consistent with this library's change-stream-driven invalidation model, and avoids the TTL-based re-listing a true absence of these events would otherwise have forced.

## Migration Plan

Add unique-key discovery and the metadata cache first, then unresolved/negative-match admission, then resolved-alias cache-miss re-verification, then asyncio parity.
