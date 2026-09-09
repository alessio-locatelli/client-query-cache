## Purpose

This capability provides bounded, process-local cache primitives that can safely store MongoDB-derived values before a public read API admits them.

## ADDED Requirements

### Requirement: Cache storage has a shared bounded budget

Each cache manager SHALL enforce one configurable weighted BSON memory budget shared by its collections. It SHALL evict least-recently-used entries as needed and SHALL reject entries larger than its maximum entry size.

#### Scenario: A new value exceeds the budget

- **WHEN** a cache admission would exceed the configured shared budget
- **THEN** the manager evicts eligible least-recently-used values or declines an oversized value without exceeding the budget

### Requirement: Cached values and aliases are isolated

The cache SHALL store BSON-derived values so caller mutation cannot change a future hit. It SHALL support document-identity aliases and namespace clearing so later coherency events can remove every affected entry. Namespace clearing and namespace creation SHALL each physically reclaim that namespace's cache budget immediately rather than leaving affected entries for eviction to reclaim later — creation reclaims because namespace-guarded entries can already be cached against a namespace that does not yet exist; an admission that raced the clear and was inserted after reclamation SHALL be detected and rolled back rather than left resident. An admission SHALL publish its entry into the namespace's reclamation index no later than the same step that confirms it does not need to be rolled back, so under normal completion a namespace clear's reclamation sweep can miss an entry only during that same bounded window. Correctness does not depend on this bound: an entry an admitting worker fails or is cancelled before publishing SHALL still be rejected at lookup by generation mismatch, degrading only to eventual reclamation via ordinary least-recently-used eviction instead of the immediate, index-driven reclaim a clear or creation otherwise provides. Rollback and index-driven removal SHALL identify and remove the exact entry they intend to remove, never a different entry that has since replaced it under the same key. Cache insertion SHALL be a conditional operation ordered by generation: it SHALL NOT replace a key's current entry with an older-generation one, regardless of arrival order. Namespace clearing SHALL also discard every alias recorded for that namespace, so a unique-key value that resolved to a document identity before the clear cannot be used to reach a cached entry for a different document admitted after the clear. An alias key SHALL identify the declared unique-key definition, its value, and its collation, so two different unique keys sharing the same value cannot collide, and two reads of the same value under different collations cannot share a resolution reached under semantics that do not apply to both. An alias SHALL be published only after the admission it accompanies passes its generation compare-and-insert, so a resolution that loses a race to a concurrent write or clear does not publish an alias for a document that no longer matches the value it was resolved from. An alias SHALL be pruned once no cached entry and no in-flight capture reference the identity it resolves to, so it does not persist unboundedly independent of the bounded LRU.

#### Scenario: A caller mutates a cached document

- **WHEN** a caller changes a document returned from a cache hit
- **THEN** a later hit returns the originally cached value rather than the caller mutation

#### Scenario: A namespace is cleared

- **WHEN** a namespace is cleared
- **THEN** every entry belonging to that namespace is removed and its weight is returned to the shared budget immediately, without waiting for least-recently-used eviction, and every alias recorded for that namespace is discarded

#### Scenario: An admission races a namespace clear

- **WHEN** an admission's generation compare-and-insert passes just before a namespace clear, and the admission's entry is physically inserted into the cache after the clear has already reclaimed the namespace
- **THEN** the manager detects the mismatch on a post-insert re-validation and removes the entry, so no entry admitted before a clear remains resident after it

#### Scenario: A rollback does not delete a newer replacement

- **WHEN** a stale admission's entry is replaced under the same cache key by a newer, valid admission before the stale admission's rollback runs
- **THEN** the rollback removes only the stale admission's own entry and leaves the newer replacement resident

#### Scenario: A late stale insertion cannot clobber a fresher entry

- **WHEN** an admission carrying an older generation reaches insertion after a different admission has already inserted a newer-generation entry under the same key
- **THEN** the older insertion is discarded and the newer entry remains resident, regardless of which admission's database read completed first

#### Scenario: A stale alias cannot reach a post-clear entry

- **WHEN** a unique-key value resolved to a document identity before a namespace clear, and a different document is admitted under that same identity after the clear
- **THEN** a later lookup by that unique-key value does not use the discarded pre-clear alias to reach the post-clear entry

#### Scenario: Different unique keys sharing a value do not collide

- **WHEN** two different documents each have a distinct unique key (e.g. `email` and `username`) resolved to the same value
- **THEN** a lookup through one key's alias reaches only the document that key resolved to, not the other document

#### Scenario: A resolution under one collation is not reused for a different collation

- **WHEN** the same unique-key value is read once under a case-insensitive collation and once under a simple/binary collation
- **THEN** the two reads resolve and use separate aliases, so a match found only under one collation's semantics is never returned for a read under the other

#### Scenario: An alias resolution loses a race and is not published

- **WHEN** a unique-key resolution's accompanying admission fails its generation compare-and-insert because a concurrent write or clear raced it
- **THEN** the manager does not publish an alias for that key value, so a later lookup by that value does not use it to reach a document it no longer matches

#### Scenario: An alias is pruned with its identity

- **WHEN** no cached entry and no in-flight capture reference a document identity that an alias resolves to
- **THEN** the alias is dropped along with that identity's generation counter

### Requirement: Namespace generations guard cache admission

Each cache namespace SHALL correspond to exactly one MongoDB namespace (`<database>.<collection>`) and SHALL maintain two monotonically increasing counters: a namespace generation advanced by every write to any document in the collection and by a namespace clear or namespace creation, and a namespace epoch advanced by a namespace clear or namespace creation, never by an ordinary write. Each document identity within a namespace SHALL additionally maintain its own monotonically increasing identity generation, advanced only by a write to that specific document.

The manager's LRU is shared across every active namespace, so every physical cache key SHALL include the owning namespace as an outer component; identity or query-shape alone SHALL NOT be used as a key, since the same value can occur in different namespaces. The cache SHALL support two entry kinds, selected by the caller admitting the result rather than implied by the read's surface shape:

- **Identity-guarded entries** SHALL record and be guarded by the identity generation of their document plus the namespace epoch; they SHALL NOT be guarded by the namespace generation, so a write to a different document in the same namespace does not invalidate them. Admitting an identity-guarded entry requires a resolved document identity before the database read, and it SHALL be keyed by (namespace, canonical identity, read shape) (e.g. projection), so a projected read and a full-document read for the same identity, or the same identity value in a different namespace, are never treated as the same cache entry.
- **Namespace-guarded entries** SHALL record and be guarded by the namespace generation alone. This kind SHALL be available for admissions that have no resolved document identity before the database read. Cache-core SHALL NOT interpret the contents of a namespace-guarded key beyond its namespace component, only require that the remainder uniquely identifies the read's shape within that namespace; the caller SHALL supply a key of (namespace, ...) that canonically encodes every output-affecting input for that read — for a unique-key lookup, the unique-key definition, value, and read shape; for a `find`/`aggregate`/`count`/`distinct` result, the operation type together with its filter/pipeline, projection, sort, limit, skip, collation, and, for `distinct`, the field name whose values are being distinguished — omitting it would let `distinct` calls on different fields collide despite returning different value lists.

Identity-guarded and namespace-guarded cache keys SHALL be disjoint, so cache insertion never has to compare a namespace generation against an identity generation and epoch pair for the same key. A database result that may be admitted SHALL capture the relevant generation(s) before the database read and SHALL use one atomic admission operation to compare the captured generation(s) with the current generation(s) and insert the result only when they all match. Invalidation's generation advancement SHALL be serialized with that admission operation, such as under the same lock or through an equivalent conditional operation. Cache lookup SHALL atomically reject an entry whose recorded generation(s) do not match the current generation(s), so generation advancement makes older entries ineligible for hits.

#### Scenario: Invalidation races an in-flight read

- **WHEN** a read captures generation 4 and an invalidation races the atomic compare-and-insert operation
- **THEN** either the admission completes first and the invalidation advances the generation afterward, or the invalidation completes first and admission rejects the result; a later cache hit cannot return a stale generation-4 value after invalidation

#### Scenario: A write to one document does not invalidate another document's identity-guarded entry

- **WHEN** a write advances one document's identity generation and the namespace generation
- **THEN** the cached identity-guarded entry for a different document in the same namespace remains admissible, because it is guarded by its own identity generation and the namespace epoch, neither of which the write advanced

#### Scenario: A write invalidates namespace-guarded entries for the whole namespace

- **WHEN** a write advances the namespace generation
- **THEN** every cached namespace-guarded entry for that namespace is rejected at the next lookup, regardless of which document the write touched

#### Scenario: A namespace clear invalidates identity-guarded entries too

- **WHEN** a namespace clear advances the namespace epoch
- **THEN** every cached identity-guarded entry in that namespace is rejected at the next lookup and any admission racing the clear is rejected, even though the affected documents' individual identity generations were not advanced

#### Scenario: A resolved unique-key read shares an entry with an `_id` read

- **WHEN** a unique-key value has a resolved alias to a document identity, and that same document is also read by `_id` with the same read shape
- **THEN** both reads use the same identity-guarded cache entry, keyed by the canonical identity and read shape rather than by the unique-key value

#### Scenario: A projected read does not collide with a full-document read

- **WHEN** a caller reads the same document identity once with a projection and once without one
- **THEN** the two reads are admitted and looked up as separate identity-guarded entries, keyed by their respective read shapes, so neither can return the other's result

#### Scenario: Namespace creation invalidates and reclaims a pre-creation namespace-guarded entry

- **WHEN** a namespace-guarded entry (e.g. a negative unique-key lookup) is admitted while its collection does not yet exist, and the collection is then created
- **THEN** the namespace generation advanced by creation makes that entry ineligible for hits, and creation physically reclaims it via the namespace's entry index the same as a clear, rather than leaving it to age out

#### Scenario: Different queries against the same namespace do not collide

- **WHEN** two `find` or `aggregate` reads against the same namespace differ in filter, pipeline, projection, sort, limit, skip, or collation
- **THEN** they are admitted and looked up as separate namespace-guarded entries, so neither can return the other's result

#### Scenario: Different `distinct` fields do not collide

- **WHEN** two `distinct` reads against the same namespace and filter differ only in the field whose values are distinguished
- **THEN** they are admitted and looked up as separate namespace-guarded entries, so neither can return the other's value list

#### Scenario: The same identity or query shape does not collide across namespaces

- **WHEN** two different namespaces each have a document with the same identity value, or each are queried with the same filter/projection/sort/limit shape
- **THEN** the entries are admitted and looked up under distinct namespace-prefixed keys, so a read in one namespace can never return a value cached for the other

### Requirement: Cache health is inspectable

The manager SHALL expose immutable health, capacity, hit, miss, eviction, and bypass observations without returning document values, queries, credentials, or resume tokens.

#### Scenario: An application inspects the manager

- **WHEN** an application requests a cache inspection snapshot
- **THEN** it receives current lifecycle and capacity information without cached document contents
