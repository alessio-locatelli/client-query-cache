# cache-core Specification

## Purpose

This capability provides bounded, process-local cache primitives that can safely store MongoDB-derived values before a public read API admits them.

## Requirements

### Requirement: Cache storage has a shared bounded budget

Each cache manager SHALL enforce one configurable weighted BSON memory budget shared by its collections. It SHALL evict least-recently-used entries as needed and SHALL reject entries larger than its maximum entry size.

#### Scenario: A new value exceeds the budget

- **WHEN** a cache admission would exceed the configured shared budget
- **THEN** the manager evicts eligible least-recently-used values or declines an oversized value without exceeding the budget

### Requirement: Cached values resist caller mutation

The cache SHALL isolate stored BSON-derived values from caller mutation.

#### Scenario: A caller mutates a cached document

- **WHEN** a caller changes a document returned from a cache hit
- **THEN** a later hit returns the originally cached value rather than the caller mutation

### Requirement: Namespace clearing reclaims entries and aliases

Namespace clearing and creation SHALL immediately reclaim affected entries and aliases from the shared cache budget.

#### Scenario: An admission is cancelled before index publication

- **WHEN** an admission fails or is cancelled before its entry reaches the namespace reclamation index
- **THEN** a mismatched generation prevents any later hit; ordinary eviction eventually reclaims the entry even if the clear cannot sweep it immediately

#### Scenario: Admission completes index publication

- **WHEN** an admission confirms that its inserted entry does not need rollback
- **THEN** it publishes that entry to the namespace reclamation index in the same step, so a clear can miss a completed admission only during that bounded window

#### Scenario: A namespace is cleared

- **WHEN** a namespace is cleared
- **THEN** every entry belonging to that namespace is removed and its weight is returned to the shared budget immediately, without waiting for least-recently-used eviction, and every alias recorded for that namespace is discarded

#### Scenario: An admission races a namespace clear

- **WHEN** an admission's generation compare-and-decide passes just before a namespace clear, and the admission's entry is physically inserted into the cache after the clear has already reclaimed the namespace
- **THEN** the manager detects the mismatch on a post-insert re-validation and removes the entry, so no entry admitted before a clear remains resident after it

### Requirement: Conditional insertion preserves the newest entry

Cache insertion and rollback SHALL preserve the newest valid entry under each physical key.

#### Scenario: A rollback does not delete a newer replacement

- **WHEN** a stale admission's entry is replaced under the same cache key by a newer, valid admission before the stale admission's rollback runs
- **THEN** the rollback removes only the stale admission's own entry and leaves the newer replacement resident

#### Scenario: A late stale insertion cannot clobber a fresher entry

- **WHEN** an admission carrying an older generation reaches insertion after a different admission has already inserted a newer-generation entry under the same key
- **THEN** the older insertion is discarded and the newer entry remains resident, regardless of which admission's database read completed first

#### Scenario: A stale pre-clear identity-guarded entry cannot outrank a valid post-clear one

- **WHEN** a stale identity-guarded entry carrying a large identity generation from before a namespace clear is still resident, and a valid identity-guarded entry with a small identity generation is admitted for the same key after the clear
- **THEN** the post-clear entry replaces the stale one, because the comparison orders by namespace epoch first — the post-clear entry's newer epoch makes it newer regardless of its smaller identity generation

### Requirement: Replacement keeps the reclamation index bounded

Replacing or evicting an entry SHALL remove its exact token from the owning namespace reclamation index.

#### Scenario: A replaced entry does not leak its index token

- **WHEN** a conditional put replaces a resident entry under the same key, and this happens repeatedly for the same key over time
- **THEN** each replacement removes the displaced entry's token from its namespace's index, so the index size tracks the number of resident entries rather than growing with the number of replacements

### Requirement: Alias keys distinguish unique definitions and collations

An alias key SHALL identify its unique-key definition, value, and collation.

#### Scenario: A stale alias cannot reach a post-clear entry

- **WHEN** a unique-key value resolved to a document identity before a namespace clear, and a different document is admitted under that same identity after the clear
- **THEN** a later lookup by that unique-key value does not use the discarded pre-clear alias to reach the post-clear entry

#### Scenario: Different unique keys sharing a value do not collide

- **WHEN** two different documents each have a distinct unique key (e.g. `email` and `username`) resolved to the same value
- **THEN** a lookup through one key's alias reaches only the document that key resolved to, not the other document

#### Scenario: A resolution under one collation is not reused for a different collation

- **WHEN** the same unique-key value is read once under a case-insensitive collation and once under a simple/binary collation
- **THEN** the two reads resolve and use separate aliases, so a match found only under one collation's semantics is never returned for a read under the other

### Requirement: Aliases publish only after valid admission

An alias SHALL be published only when its accompanying admission passes its generation decision.

#### Scenario: An alias resolution loses a race and is not published

- **WHEN** a unique-key resolution's accompanying admission fails its generation compare-and-decide because a concurrent write or clear raced it
- **THEN** the manager does not publish an alias for that key value, so a later lookup by that value does not use it to reach a document it no longer matches

### Requirement: Unreferenced aliases are pruned

An alias SHALL be pruned when no cached identity-guarded entry or in-flight capture references its resolved identity.

#### Scenario: An alias is pruned with its identity

- **WHEN** no cached identity-guarded entry and no in-flight capture reference a document identity that an alias resolves to
- **THEN** the alias is dropped along with that identity's generation counter

### Requirement: Namespace generations track writes and lifecycle events

Each MongoDB namespace SHALL track a monotonically increasing generation advanced by any write, clear, or creation.

#### Scenario: A write invalidates namespace-guarded entries for the whole namespace

- **WHEN** a write advances the namespace generation
- **THEN** every cached namespace-guarded entry for that namespace is rejected at the next lookup, regardless of which document the write touched

#### Scenario: Namespace creation invalidates and reclaims a pre-creation namespace-guarded entry

- **WHEN** a namespace-guarded entry (e.g. a negative unique-key lookup) is admitted while its collection does not yet exist, and the collection is then created
- **THEN** the namespace generation advanced by creation makes that entry ineligible for hits, and creation physically reclaims it via the namespace's entry index the same as a clear, rather than leaving it to age out

### Requirement: Namespace epochs track clears and creation

Each MongoDB namespace SHALL track a monotonically increasing epoch advanced by clears and creation, never by ordinary writes.

#### Scenario: A namespace clear invalidates identity-guarded entries too

- **WHEN** a namespace clear advances the namespace epoch
- **THEN** every cached identity-guarded entry in that namespace is rejected at the next lookup and any admission racing the clear is rejected, even though the affected documents' individual identity generations were not advanced

### Requirement: Identity generations track document writes

Each document identity SHALL track a monotonically increasing generation advanced only by writes to that document.

#### Scenario: A write to one document does not invalidate another document's identity-guarded entry

- **WHEN** a write advances one document's identity generation and the namespace generation
- **THEN** the cached identity-guarded entry for a different document in the same namespace remains admissible, because it is guarded by its own identity generation and the namespace epoch, neither of which the write advanced

### Requirement: Admission and lookup reject stale generations

Admission and lookup SHALL reject entries whose captured generations no longer match current generations.

#### Scenario: An invalidation occurs after physical insertion

- **WHEN** an invalidation advances a generation between admission compare-and-decide and physical insertion
- **THEN** post-insert re-validation rolls back the inserted entry on a mismatch

#### Scenario: Invalidation races an in-flight read

- **WHEN** a read captures generation 4 and an invalidation races the atomic compare-and-decide step
- **THEN** either the compare-and-decide completes first and the invalidation advances the generation afterward, or the invalidation completes first and the compare-and-decide rejects the result; a later cache hit cannot return a stale generation-4 value after invalidation, whether the invalidation raced the compare-and-decide or the separate physical insertion that follows it

### Requirement: Entry kinds have disjoint key spaces

Identity-guarded and namespace-guarded entries SHALL use disjoint physical key spaces so insertion never compares unlike generation guards under one key.

#### Scenario: Two entry kinds share a logical lookup shape

- **WHEN** an identity-guarded and a namespace-guarded result have otherwise matching lookup inputs
- **THEN** their physical keys remain distinct and neither can replace the other

### Requirement: Identity-guarded keys distinguish read shapes and namespaces

An identity-guarded entry SHALL be keyed by namespace, canonical identity, and read shape.

#### Scenario: A resolved unique-key read shares an entry with an `_id` read

- **WHEN** a unique-key value has a resolved alias to a document identity, and that same document is also read by `_id` with the same read shape
- **THEN** both reads use the same identity-guarded cache entry, keyed by the canonical identity and read shape rather than by the unique-key value

#### Scenario: A projected read does not collide with a full-document read

- **WHEN** a caller reads the same document identity once with a projection and once without one
- **THEN** the two reads are admitted and looked up as separate identity-guarded entries, keyed by their respective read shapes, so neither can return the other's result

#### Scenario: The same identity or query shape does not collide across namespaces

- **WHEN** two different namespaces each have a document with the same identity value, or each are queried with the same filter/projection/sort/limit shape
- **THEN** the entries are admitted and looked up under distinct namespace-prefixed keys, so a read in one namespace can never return a value cached for the other

### Requirement: Namespace-guarded keys encode every output-affecting input

A namespace-guarded entry SHALL use a namespace-prefixed key that canonically encodes every output-affecting input.

#### Scenario: Different queries against the same namespace do not collide

- **WHEN** two `find` or `aggregate` reads against the same namespace differ in filter, pipeline, projection, sort, limit, skip, or collation
- **THEN** they are admitted and looked up as separate namespace-guarded entries, so neither can return the other's result

#### Scenario: Different `distinct` fields do not collide

- **WHEN** two `distinct` reads against the same namespace and filter differ only in the field whose values are distinguished
- **THEN** they are admitted and looked up as separate namespace-guarded entries, so neither can return the other's value list

### Requirement: Cache health is inspectable

The manager SHALL expose immutable health, capacity, hit, miss, eviction, and bypass observations without returning document values, queries, credentials, or resume tokens.

#### Scenario: An application inspects the manager

- **WHEN** an application requests a cache inspection snapshot
- **THEN** it receives current lifecycle and capacity information without cached document contents
