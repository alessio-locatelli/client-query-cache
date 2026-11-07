# cache-core Specification

## Purpose

This capability provides bounded, process-local cache primitives that can safely store MongoDB-derived values before a public read API admits them.

## Requirements

### Requirement: Cache storage has a shared bounded budget

Each cache manager SHALL enforce one configurable weighted BSON memory budget, `CacheCoreConfig.budget_bytes`, shared by its collections. It SHALL evict least-recently-used entries as needed and SHALL reject entries larger than its maximum entry size.

#### Scenario: A new value exceeds the budget

- **WHEN** a cache admission would exceed the configured `budget_bytes`
- **THEN** the manager evicts eligible least-recently-used values or declines an oversized value without exceeding the budget

### Requirement: Cache budget fields require built-in integers

Each cache-budget field SHALL accept only an exact built-in integer. Boolean values, integer subclasses, floats including NaN and infinities, strings, null values, and other types SHALL raise the public configuration error at configuration construction, before comparisons or storage initialization.

#### Scenario: Invalid runtime budget input

- **WHEN** either `budget_bytes` or `max_entry_bytes` receives a non-built-in-integer value
- **THEN** construction raises `CacheConfigurationError` naming the invalid field
- **AND** no implicit conversion occurs

### Requirement: Cache budget ranges remain enforceable

`budget_bytes` and `max_entry_bytes` SHALL be positive, and `max_entry_bytes` SHALL NOT exceed `budget_bytes`. Invalid relationships SHALL raise the public configuration error at configuration construction. Public configuration guidance SHALL state these constraints and the rejected input types.

#### Scenario: Valid boundary values

- **WHEN** both values are positive built-in integers and `max_entry_bytes` equals `budget_bytes`
- **THEN** construction succeeds with the values unchanged

#### Scenario: An invalid range or relationship is supplied

- **WHEN** either value is zero or negative, or `max_entry_bytes` exceeds `budget_bytes`
- **THEN** construction raises `CacheConfigurationError` describing the violated constraint

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

### Requirement: Tracked namespace state is bounded

Each cache core SHALL retain state for no more than its configured `max_namespaces` limit. The limit SHALL be a positive built-in integer. Requests for an untracked namespace at capacity SHALL bypass caching with the `namespace_capacity` reason while preserving native MongoDB behavior.

#### Scenario: Namespace capacity is exhausted

- **WHEN** a request first accesses a namespace while the cache core tracks `max_namespaces` other namespaces
- **THEN** it executes through MongoDB and records `namespace_capacity` without adding namespace state

#### Scenario: An invalid namespace limit is configured

- **WHEN** `max_namespaces` is zero, negative, or not a built-in integer
- **THEN** cache configuration raises `CacheConfigurationError` before cache use

### Requirement: Dropped namespaces release state safely

Processing a collection drop SHALL invalidate its entries and aliases, release its tracked namespace state, and make capacity available to another namespace. A capture made against the released state SHALL NOT admit after the name is reused.

#### Scenario: A dropped namespace releases capacity

- **WHEN** a tracked collection is dropped and another collection is requested afterward
- **THEN** the dropped state and its entries are reclaimed and the new collection can be tracked

#### Scenario: A delayed admission crosses drop and recreation

- **WHEN** an admission captured before a drop completes after the same collection name has been recreated
- **THEN** the old capture is rejected even if the new namespace has no cached entries

### Requirement: Process-local namespace metadata caches are bounded

Each process-local collection-metadata and unique-key-metadata cache SHALL retain no more than `max_namespaces` namespace entries and SHALL evict its oldest stored metadata when full.

#### Scenario: Metadata cache capacity is reached

- **WHEN** metadata is stored for more than `max_namespaces` namespaces
- **THEN** each metadata cache retains at most `max_namespaces` entries and keeps the most recently stored entries

### Requirement: Identity generations track document writes

Each document identity SHALL track a monotonically increasing generation advanced only by writes to that document.

#### Scenario: A write to one document does not invalidate another document's identity-guarded entry

- **WHEN** a write advances one document's identity generation and the namespace generation
- **THEN** the cached identity-guarded entry for a different document in the same namespace remains admissible, because it is guarded by its own identity generation and the namespace epoch, neither of which the write advanced

### Requirement: Identity matching follows MongoDB numeric equality

Identity-guarded keys and write routing SHALL treat document identities as equal when they differ only in numeric BSON type, among 32-bit integer, 64-bit integer, double and decimal values of exactly equal value, at any nesting depth. A processed write to such a document SHALL invalidate every cached entry for an equal identity. Identities with unequal exact values SHALL remain distinct.

#### Scenario: A cached identity is written under another numeric type

- **WHEN** a read by `_id` value `1` cached a document whose stored `_id` is decimal `1`, or whose embedded `_id` holds that decimal where the read holds the integer, and the manager processes an update to that document
- **THEN** the next read cannot return the pre-invalidation cached result

#### Scenario: Unequal numeric identities stay distinct

- **WHEN** one document has the double `_id` `19.99` and another has the decimal `_id` `19.99`, and a caller reads each by its own `_id` value
- **THEN** each read returns its own document, because MongoDB does not consider the two values equal

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

A namespace-guarded entry SHALL use a namespace-prefixed key encoding every output-affecting input. Distinct query identities SHALL have distinct physical keys. Reuse SHALL be allowed only by an explicitly specified semantic-equivalence or compatible-result contract; without such a contract, differing inputs SHALL NOT reuse a result.

#### Scenario: Different queries against the same namespace do not collide

- **WHEN** two `find` or `aggregate` reads against the same namespace differ in filter, pipeline, projection, sort, limit, skip, or collation
- **THEN** distinct query identities have separate physical keys and cannot supply one another's results except through explicitly supported compatible-result lookup; sharing a physical identity requires an explicitly supported equivalence

#### Scenario: Different `distinct` fields do not collide

- **WHEN** two `distinct` reads against the same namespace and filter differ only in the field whose values are distinguished
- **THEN** they are admitted and looked up as separate namespace-guarded entries, so neither can return the other's value list

### Requirement: Cache health is inspectable

With telemetry enabled, the manager SHALL expose immutable health, capacity (including the configured `budget_bytes`), hit, miss, eviction, and bypass observations through publicly importable result types, without returning document values, queries, credentials, or resume tokens.

#### Scenario: An application inspects the manager

- **GIVEN** telemetry is enabled
- **WHEN** an application requests a cache inspection snapshot
- **THEN** it receives immutable lifecycle, capacity (including the configured `budget_bytes`), hit, miss, eviction, and bypass observations in publicly importable result types, without document values, queries, credentials, or resume tokens

### Requirement: Manager inspection is synchronous and read-only

With telemetry enabled, both execution models SHALL provide synchronous, local manager inspection that performs no database I/O, starts no stream, resets no counter, and changes no cache state.

#### Scenario: An asyncio application inspects statistics

- **GIVEN** telemetry is enabled
- **WHEN** an application requests a snapshot from an asyncio manager
- **THEN** it receives an immutable result synchronously without awaiting or performing database I/O

#### Scenario: Repeated inspection is read-only

- **GIVEN** telemetry is enabled
- **WHEN** an application inspects a manager repeatedly, including after close
- **THEN** inspection exposes the available lifecycle/statistics observations without reopening streams or resetting cumulative counters

### Requirement: Advanced cache inspection remains available

With telemetry enabled, the advanced cache inspection interface SHALL remain available with measurements equivalent to manager inspection.

#### Scenario: An advanced caller inspects the cache

- **GIVEN** telemetry is enabled
- **WHEN** a caller uses the advanced cache inspection interface
- **THEN** it exposes equivalent cache measurements for the same underlying state

### Requirement: Bypass recording has fixed safe reasons

Every ordinary bypass recording SHALL increment the existing ordinary aggregate count and exactly one count from a fixed, publicly typed reason vocabulary.

#### Scenario: A caller inspects the reason vocabulary

- **WHEN** a caller inspects the public bypass reason type
- **THEN** it distinguishes session-bound reads, incompatible read profiles, unsupported options, unsafe filters, unsafe projections, unsafe pipelines, uncanonicalizable keys, missing collections, views, time-series collections, unavailable metadata, unavailable streams, invalidated admissions, and unspecified advanced recording

#### Scenario: A missing collection produces a bypass

- **WHEN** an otherwise eligible read targets a collection that does not exist
- **THEN** its ordinary bypass recording is classified as a missing collection rather than as an unhealthy stream or incompatible read profile

#### Scenario: A read has several bypass conditions

- **WHEN** a read is session-bound and also has unsupported options
- **THEN** its facade-level bypass recording has one session reason according to the documented precedence, rather than counting both conditions

#### Scenario: An admission loses continuity

- **WHEN** a previously eligible admission is declined because its availability generation changed while the database is currently available
- **THEN** the existing bypass recording is classified as an invalidated admission without claiming that the stream is currently unavailable

#### Scenario: Advanced callers record an unspecified bypass

- **WHEN** an advanced caller uses the existing explicit bypass-recording interface without providing a reason
- **THEN** the call remains supported and increments the ordinary aggregate and the unspecified reason

### Requirement: Bypass counts retain recording-event semantics

Bypass counts SHALL preserve existing recording-event semantics rather than represent one outcome per application request.

#### Scenario: An application request produces bypass recordings

- **WHEN** an application request produces ordinary bypass recording events
- **THEN** each event increments the ordinary aggregate and one reason count without being redefined as one outcome per request

### Requirement: Bypass reason snapshots agree with their aggregate

A snapshot SHALL expose immutable ordinary reason counts whose sum equals its ordinary bypass aggregate, without promising an atomic sample of independently observed capacity fields.

#### Scenario: Concurrent recordings and inspection

- **WHEN** bypass recordings race snapshot creation
- **THEN** each returned snapshot's immutable ordinary reason counts sum to that snapshot's ordinary bypass aggregate, without promising a single atomic sample of independently observed capacity fields

### Requirement: Oversized-result recordings remain separate

Oversized-result recordings SHALL NOT increment the ordinary bypass aggregate or ordinary reason counts.

#### Scenario: A result exceeds the entry limit

- **WHEN** a cache admission is declined because its encoded result is oversized
- **THEN** the oversized count increments without incrementing the ordinary bypass aggregate or any ordinary reason

### Requirement: Manager access preserves stream-cost inspection

Both manager execution models SHALL expose the existing per-database stream-cost snapshots and active-database discovery through synchronous, read-only manager accessors. Their measurement scope, cumulative counts, bounded lag samples, and clock limitations SHALL remain unchanged.

#### Scenario: A caller reads stream measurements through a manager

- **WHEN** a caller requests stream-cost measurements or active measurement databases through the manager
- **THEN** the observations agree with the existing advanced inspection source for the same underlying state, without additional database requests or state mutation

### Requirement: Find limit compatibility preserves physical key separation

Different find limits SHALL remain distinct physical query identities. Limit subsumption SHALL use a separate compatibility relation and SHALL NOT remove the limit from the source's physical key.

#### Scenario: A covering source supplies a distinct limited shape

- **WHEN** a cached limit-100 source supplies an otherwise identical limit-10 request
- **THEN** the source retains its limit-100 physical key and the request is satisfied through compatibility rather than key equivalence

### Requirement: Find compatibility lookup has one cache outcome

An eligible find lookup SHALL check its exact key and supported covering entries before recording its outcome. A compatible hit SHALL record one hit, no miss, and normal LRU access for the resident source entry. Failure to find either an exact or compatible valid entry SHALL record one miss. Existing stream-unavailable bypass accounting SHALL be preserved.

#### Scenario: Exact lookup fails but compatibility succeeds

- **WHEN** a positive-limit lookup lacks a valid exact entry but finds a valid covering source
- **THEN** hits increase by one, misses remain unchanged, and subsequent budget pressure treats the source as recently used

#### Scenario: Every candidate is absent or invalid

- **WHEN** neither the exact key nor any covering candidate supplies a valid result
- **THEN** misses increase by one without an intermediate miss per candidate

#### Scenario: Database availability prevents lookup

- **WHEN** the source's database stream is unavailable
- **THEN** no compatible hit is recorded and the existing stream-unavailable bypass path is retained

### Requirement: Compatibility metadata follows resident source ownership

Compatibility lookup SHALL be confined to the requested namespace and query family, excluding only the limit from that family. Metadata SHALL reference admitted source entries without duplicating result payloads or creating entries for smaller limits. Replacement, eviction, rollback, namespace reclamation, and close SHALL remove obsolete references without deleting newer replacements. Metadata growth SHALL follow resident sources rather than historical queries.

#### Scenario: Unrelated cache contents grow

- **WHEN** unrelated namespaces and query families are added to the shared cache
- **THEN** a compatible find lookup examines only its own family rather than scanning the shared cache or whole namespace

#### Scenario: Many narrower cursors use one source

- **WHEN** many distinct smaller positive limits hit the same cached source
- **THEN** resident entry count and payload weight do not increase merely to represent those narrower queries

#### Scenario: Eviction precedes compatibility publication

- **WHEN** a source is evicted while admission publishes its compatibility metadata
- **THEN** the obsolete token is reclaimed and it cannot later supply a hit

#### Scenario: An obsolete token races replacement

- **WHEN** cleanup for an older source runs after a newer entry for that source key has been published
- **THEN** cleanup removes only the obsolete entry's references and leaves the newer source discoverable

#### Scenario: Namespace clear or manager close reclaims metadata

- **WHEN** a namespace is cleared or created, or the manager closes
- **THEN** its compatibility references are reclaimed along with the existing resident-entry lifecycle

### Requirement: Compatible sources retain namespace and availability guards

Compatible lookup SHALL validate the actual resident source with the same namespace-generation and database-availability rules as exact namespace lookup. Compatibility metadata SHALL NOT make stale, rolled-back, evicted, or otherwise ineligible sources reusable. Admission SHALL retain existing generation and availability capture checks.

#### Scenario: A write is processed before the narrower execution

- **WHEN** a larger result is cached and the manager processes a namespace write before consuming a new smaller-limit cursor
- **THEN** the older source is rejected and the new execution reads from MongoDB

#### Scenario: Stream continuity is lost and restored

- **WHEN** stream uncertainty invalidates the larger source before a subsequent smaller-limit execution
- **THEN** availability bypass or recovery guards prevent reuse of the pre-transition source

#### Scenario: Invalidation races candidate selection

- **WHEN** the namespace generation changes after a covering token is selected but before its validity decision
- **THEN** the candidate is rejected under the same lookup boundary as an exact entry

### Requirement: Proven find filter permutations share one namespace key

Find filters in the explicitly supported equivalence set SHALL share their filter representation. All other output-affecting inputs SHALL remain in the namespace-prefixed physical key, and unsupported filter forms SHALL retain their existing distinctions.

#### Scenario: Proven predicate permutations share one source key

- **WHEN** two find filters differ only in supported top-level scalar predicate ordering and all other key inputs match
- **THEN** they use one namespace-prefixed physical key rather than storing duplicate payloads

#### Scenario: Literal order is not an equivalence

- **WHEN** two find filters change field order inside a literal embedded document
- **THEN** the order-sensitive literal representations keep their physical keys distinct

### Requirement: Resident entries share namespace identity

Resident entries and their physical keys SHALL reference one namespace identifier per registered namespace instead of retaining a separate equal identifier for each admission. Sharing SHALL NOT change key equality, eviction, reclamation, or lookup outcomes.

#### Scenario: Entries admitted through different requests

- **WHEN** several reads of one namespace, each supplying its own equal namespace identifier, are admitted as identity-guarded and namespace-guarded entries
- **THEN** every resident entry and physical key references the same namespace identifier, and lookups through new equal identifiers still hit

### Requirement: Unaliased identities retain no alias storage

Identity bookkeeping SHALL retain alias storage only while at least one unique-key alias resolves to that identity. Alias publication, displacement, invalidation, pruning, and namespace reclamation SHALL keep their existing outcomes.

#### Scenario: An identity is cached without an alias

- **WHEN** an identity-guarded entry is admitted without a unique-key alias
- **THEN** its identity bookkeeping retains no alias storage of its own

#### Scenario: An alias moves to another identity

- **WHEN** an alias published for one identity is later published for another identity, or its identity is written or reclaimed
- **THEN** the alias resolves only to its current identity, and an identity left without aliases again retains no alias storage

### Requirement: Order-sensitive key nodes carry no redundant layers

A canonical cache key SHALL represent each order-sensitive mapping, sequence, and numeric-subtype value, and the sorted representation of a scalar find filter, as one tagged node whose payload is canonicalized in place, without an enclosing generic-sequence layer. An order-sensitive mapping SHALL keep its field names and values in one payload tuple, without a tuple per field.

#### Scenario: A one-predicate filter forms its key

- **WHEN** a generic `find_one` filter `{"code": "C0000001"}` forms its namespace-guarded key
- **THEN** the filter's part of the key consists of two tuples: the tagged mapping node and its payload `("code", "C0000001")`

#### Scenario: Nested order-sensitive values form a key

- **WHEN** a filter contains an embedded document, an array, a double, and a 64-bit integer
- **THEN** each of these values appears in the key as one tagged node, and no generic-sequence node directly contains a private key tag

#### Scenario: A scalar find filter forms its family

- **WHEN** a `find()` filter qualifies for sorted scalar predicates
- **THEN** its family holds the sorted filter as one tagged node around the ordered mapping node, without a generic-sequence layer between them

### Requirement: Compact key nodes keep key equality

The compact representation SHALL NOT change which inputs share a canonical key or a find family. Bool and integer values, numeric subtypes in discriminators, mapping field order in order-sensitive inputs, and mappings versus sequences SHALL stay distinct. Equal keys SHALL hash equally. Unhashable values and NaN SHALL remain uncanonicalizable, so their reads bypass the cache.

#### Scenario: Distinguished inputs keep separate keys

- **WHEN** two otherwise identical discriminators differ only in `True` versus `1`, `1` versus `1.0` or `Int64(1)`, the field order of an embedded filter document, or a mapping versus an equivalent pair sequence
- **THEN** their canonical keys are unequal

#### Scenario: Numerically equal identities share a key

- **WHEN** identities `1`, `1.0`, `Int64(1)`, and `Decimal128("1")` are canonicalized as identities, alone or embedded in a document
- **THEN** they produce equal keys with equal hashes

#### Scenario: Non-reflexive values are rejected

- **WHEN** a discriminator contains a double NaN inside an order-sensitive node, or an identity is a decimal NaN
- **THEN** canonicalization fails as uncanonicalizable and the read bypasses the cache

### Requirement: Re-canonicalization reuses canonical subtrees

Canonicalizing an already canonical key SHALL return that key object. A structure that embeds canonical subtrees, such as a find or generic `find_one` discriminator built around a canonical family, filter, or read shape, SHALL reference those subtrees without rebuilding them.

#### Scenario: A discriminator wraps a canonical family

- **WHEN** a find discriminator is built from a canonical family and a limit
- **THEN** the discriminator references the same family object, and canonicalizing the discriminator again returns the same discriminator object

#### Scenario: A family arrives in raw and canonical form

- **WHEN** one find family is canonicalized from its raw read shape and another copy is decoded from its canonical wire form
- **THEN** both produce equal keys with equal family hashes, so exact lookup and limit-compatible lookup reach the same resident entries

### Requirement: Read executions reuse prepared discriminator trees

In both execution models, cache-eligible `find`, `aggregate`, `count_documents`, and `distinct` executions SHALL canonicalize their raw discriminator tree once and reuse its canonical tree for lookup and admission. A find execution SHALL also reuse its canonical family for compatibility checks and source metadata. Constant-size wrappers and canonical-key passthrough SHALL NOT rebuild the query tree.

#### Scenario: An exact hit is served

- **WHEN** an eligible read executes against a valid exact cache entry
- **THEN** it performs one raw discriminator-tree canonicalization and returns the cached result without another tree traversal for key preparation

#### Scenario: A miss is admitted

- **WHEN** an eligible read misses and successfully completes its native result
- **THEN** lookup and admission share the prepared canonical tree instead of independently canonicalizing the raw discriminator

#### Scenario: A find uses a covering source

- **WHEN** a positive-limit find checks a compatible resident source after its exact lookup misses
- **THEN** compatibility checks reuse the prepared family without canonicalizing the raw family again
- **AND** the lookup retains one hit and no miss when a covering source succeeds

#### Scenario: A find execution is restarted

- **WHEN** a find cursor is rewound or cloned and its final options change before the next execution
- **THEN** that execution prepares its own key from the final native options rather than reusing an earlier execution's key

### Requirement: Read key preparation preserves bypass precedence

Read key preparation SHALL retain the existing order of request-level bypass conditions, unsafe filter, unsafe projection or pipeline, uncanonicalizable key, and collection eligibility. Canonicalization failure SHALL record `uncanonicalizable_key` only when no earlier condition applies, then delegate to native execution with the original arguments and errors, without cache lookup or admission.

#### Scenario: Unsafe input also contains an uncanonicalizable value

- **WHEN** a request has an unsafe filter, projection, or pipeline and its discriminator also contains an uncanonicalizable value
- **THEN** the facade records the corresponding unsafe reason rather than an uncanonicalizable-key reason
- **AND** it performs no raw discriminator canonicalization

#### Scenario: A request-level bypass precedes unsafe input

- **WHEN** a request is session-bound, has an incompatible read profile, or has unsupported options, and also has unsafe or uncanonicalizable key inputs
- **THEN** its existing request-level reason wins and no discriminator canonicalization is attempted

#### Scenario: A safe discriminator cannot be canonicalized

- **WHEN** an otherwise safe request contains a NaN or unhashable discriminator value
- **THEN** it records one uncanonicalizable-key bypass before any collection eligibility probe
- **AND** native execution determines the returned result or error

### Requirement: Process-local retention limits are optional

`CacheCoreConfig` SHALL expose `max_entries` and `max_key_bytes`, each defaulting to `None` (disabled) and otherwise accepting only a positive exact built-in integer. Invalid input SHALL raise `CacheConfigurationError` naming the field. Limits SHALL apply independently across all collections of one process-local manager in both execution models.

#### Scenario: Existing admission defaults are preserved

- **WHEN** neither limit is configured
- **THEN** admission has no additional count or key-size restriction and performs no key-size accounting

#### Scenario: A limit is configured independently

- **WHEN** one limit is a positive built-in integer and the other is `None`
- **THEN** construction succeeds and only the configured restriction applies

#### Scenario: Invalid retention limit input

- **WHEN** either limit is zero, negative, a Boolean, an integer subclass, a float, a string or another non-null non-integer value
- **THEN** configuration construction raises `CacheConfigurationError` before storage initialization

### Requirement: Retained record capacity includes aliases

After each completed mutation, resident values plus retained unique-key aliases SHALL NOT exceed `max_entries` when configured. Replacement SHALL count only the surviving record. Value admission SHALL reclaim aliases before evicting least-recently-used values as needed. Alias publication at capacity SHALL be declined without displacing a resident value. Captures and registered namespace state SHALL NOT count as resident records.

#### Scenario: Small results exhaust record capacity before BSON capacity

- **WHEN** a new value would exceed the record limit while BSON space remains
- **THEN** aliases are reclaimed first and least-recently-used values are evicted only as needed to admit the value within both limits

#### Scenario: One identity has many aliases

- **WHEN** publishing an additional unique-key alias would exceed the record limit
- **THEN** that alias is not retained, the native result and any admitted identity value remain available, and one alias retention decline with reason `entry_capacity` is recorded

#### Scenario: Replacement and concurrent mutation

- **WHEN** replacement, alias displacement and admission race
- **THEN** the completed mutations retain at most the configured number of records without deleting a newer replacement

### Requirement: Retained keys have a defined size charge

With `max_key_bytes` enabled, each value or alias SHALL have a per-record charge: the sum of shallow Python object sizes over its canonical key roots, recursively visiting tuples and counting each object identity once within that record. Shared namespace identifiers and canonical tag singletons SHALL be excluded. Scalar referents, storage indexes and allocator overhead SHALL be excluded; the charge SHALL NOT claim actual retained memory.

#### Scenario: A key contains repeated canonical subtrees

- **WHEN** a value key references the same tuple subtree more than once
- **THEN** the subtree contributes once to that record's charge, independently of sharing with other records

#### Scenario: Identity and alias roots

- **WHEN** sizing an identity value or unique-key alias
- **THEN** the charge includes identity plus read shape for the value, or alias key plus resolved identity for the alias

### Requirement: Key-size declines preserve native delivery

A candidate whose key charge exceeds `max_key_bytes` SHALL NOT be retained. Equality SHALL be admitted if other checks pass. A sizing failure SHALL decline retention. These decisions SHALL preserve native results, errors and cursor delivery, leave existing valid entries intact, and record respectively `key_size_limit` or `key_size_unavailable` once per declined value or alias publication.

#### Scenario: A large query returns a small result

- **WHEN** the encoded result fits the BSON limits but its key charge exceeds the configured key limit
- **THEN** the complete native result is delivered and the candidate is not retained

#### Scenario: Only a non-composite identity admission's alias is too large

- **WHEN** a non-composite identity admission's value fits its limits but its accompanying alias does not fit the key limit
- **THEN** the identity value can be admitted and only alias publication is declined

#### Scenario: A size boundary or sizing failure is reached

- **WHEN** the key charge equals the configured limit or sizing cannot complete
- **THEN** equality passes the key check, while failure declines retention without surfacing a sizing error to the read caller

### Requirement: Retention accounting follows current ownership

Eviction, alias removal, invalidation, replacement, namespace reclamation and close SHALL release the corresponding retention capacity. In-flight captures SHALL retain their existing generation and availability guards. Dropping an alias for capacity SHALL NOT invalidate its identity value. A closed manager SHALL report zero retained values and aliases.

#### Scenario: A capture outlives its resident entry

- **WHEN** eviction removes the last resident value while an identity capture remains active
- **THEN** any still-retained alias consumes capacity, and a later capacity reclamation can remove that alias without reviving stale admission

#### Scenario: A write or namespace lifecycle event releases records

- **WHEN** the existing lifecycle rules reclaim values or aliases
- **THEN** released records cease consuming capacity and later admission can reuse it

### Requirement: Retention inspection separates values and aliases

Cache snapshots SHALL expose `max_entries`, `max_key_bytes` and `alias_count`, retaining `entry_count` as the count of resident values and `used_bytes` as stored BSON bytes. Alias reclamation SHALL NOT increment value eviction counts. Inspection SHALL remain local and read-only without exposing keys.

#### Scenario: A miss admits a value but declines its alias

- **WHEN** alias capacity or key size prevents publication
- **THEN** inspection shows the retained value, no new alias and one matching retention decline, without changing bypass or oversized counts or reclassifying the original miss

#### Scenario: Repeated inspection

- **WHEN** either manager API or its advanced core is inspected repeatedly
- **THEN** equivalent snapshots expose the configured limits and counts without traversing retained keys or changing counters

### Requirement: Retention declines have separate recording semantics

Snapshots SHALL expose immutable cumulative `retention_declines` counts by record kind (`namespace_value`, `identity_value`, `alias`) and reason (`key_size_limit`, `key_size_unavailable`, `entry_capacity`). Each declined candidate SHALL record once. Unused alternative representations, aliases skipped after an identity-key failure and reclaimed old records SHALL NOT count as declines. These events SHALL NOT increment bypass or oversized counters.

#### Scenario: A value fits but its alias does not

- **WHEN** admission retains a value and declines its alias due to key size or count capacity
- **THEN** exactly one matching alias decline is recorded and the read's hit/miss and bypass observations retain their existing meanings

#### Scenario: Existing telemetry is collected

- **WHEN** an OpenTelemetry collection follows a retention decline
- **THEN** ordinary bypass totals, bypass reason series and oversized totals remain unchanged by that decline
- **AND** the decline is available through snapshot inspection without adding query-derived labels or redefining existing instruments

### Requirement: Count-enabled unique-key admission prefers a useful pair

With `max_entries` enabled, unique-key admission SHALL prefer an identity value and its alias as one useful pair, without adding a namespace value. If the pair cannot fit, it SHALL attempt the original namespace result instead. Pair failure SHALL NOT strand a newly admitted identity value or alias. Alias publication SHALL require a valid resident identity value; later alias retention SHALL follow existing capture and invalidation rules.

#### Scenario: One record fits

- **WHEN** an empty cache has `max_entries=1` and all candidate keys and value payloads individually fit
- **THEN** only the namespace value is retained and repeated original queries can hit
- **AND** one alias `entry_capacity` decline is recorded for the impossible pair without sizing its keys

#### Scenario: Two records fit

- **WHEN** an empty cache has `max_entries=2` and the identity key, alias key and single value payload fit
- **THEN** the identity value and alias are retained, the namespace value is absent, and both original unique-key and matching identity queries can hit

#### Scenario: Three records fit

- **WHEN** an empty cache has `max_entries=3` and the pair fits
- **THEN** only the pair is retained for that query, leaving a slot for another record

#### Scenario: The BSON budget fits only one value payload

- **WHEN** count capacity permits the pair but storing two copies of the result would exceed the BSON budget
- **THEN** pair admission requires only the identity value's usual BSON charge and no redundant namespace payload

#### Scenario: The original query key is too large

- **WHEN** the pair fits but the unused namespace key would fail its key check
- **THEN** the pair is retained without sizing or recording a decline for that unused key

### Requirement: Pair admission respects global occupancy and eviction

Pair feasibility SHALL use current manager-wide occupancy, exact replacements and alias reclamation atomically. It SHALL reuse valid matching records and respect normal value LRU. It SHALL NOT evict unrelated values beyond those needed to admit the identity value alone solely to obtain an alias slot. A failed pair plan SHALL make no destructive changes before namespace fallback is evaluated. Cleanup SHALL preserve newer replacements.

#### Scenario: A full cache cannot spare an alias slot

- **WHEN** a cache with `max_entries=2` holds two unrelated values and admitting the identity value alone would evict one
- **THEN** the pair does not evict the second unrelated value for its alias
- **AND** normal single-value admission of the namespace fallback is attempted instead

#### Scenario: Alias reclamation supplies the second slot

- **WHEN** the pair fits after reclaiming existing aliases and any normal identity-value LRU victims
- **THEN** those aliases can be reclaimed and the pair admitted without extra unrelated-value eviction for its alias

#### Scenario: Matching records already occupy capacity

- **WHEN** the matching identity value or alias already resides in the cache
- **THEN** the pair plan counts only net record and byte changes and validates their exact ownership and generations

#### Scenario: A redundant namespace record already exists

- **WHEN** replacing the exact current namespace record with the pair makes the pair feasible
- **THEN** that record can be retired as part of the atomic replacement without treating a newer replacement as redundant

#### Scenario: Admissions race across namespaces

- **WHEN** concurrent admissions compete for the same manager-wide capacity
- **THEN** each committed plan uses the latest occupancy and leaves the combined bound intact

#### Scenario: A warm hit changes the planned LRU victim

- **WHEN** a warm hit promotes a value after tentative victim selection but before eviction commits
- **THEN** admission revalidates victim selection against the new order without evicting an extra unrelated value for an alias

### Requirement: Pair fallback and admission outcomes remain explicit

With `max_entries` enabled, composite admission SHALL report admitted only for a valid resident pair or eligible namespace fallback. A fitting identity value alone SHALL NOT establish success. If neither representation fits, it SHALL report a retention decline. Stale and unavailable outcomes SHALL retain their generation and availability meanings. With `max_entries=None`, existing composite targets and outcomes SHALL remain, except for explicitly enabled key-size declines.

#### Scenario: The alias key cannot be retained

- **WHEN** the pair's alias key exceeds its limit but the original namespace key and result fit
- **THEN** namespace fallback is admitted without a newly stranded identity value or alias, and the outcome is admitted rather than stale

#### Scenario: No candidate value fits

- **WHEN** the pair fails and the namespace fallback key also fails its key check
- **THEN** admission reports a retention decline without changing existing valid records

#### Scenario: A write races preparation

- **WHEN** a sizing callback or another thread invalidates the capture before publication
- **THEN** the existing stale or unavailable outcome applies without publishing stale values or aliases

#### Scenario: Only the key-size limit is enabled

- **WHEN** `max_entries=None` and `max_key_bytes` is configured
- **THEN** the existing namespace-value, identity-value and alias publication policy is retained subject to its individual key checks, without enabling the pair-and-fallback policy

### Requirement: Pair fallback decline observations are deterministic

Count-enabled unique-key admission SHALL record one blocking pair decline plus any namespace-fallback decline. Structurally impossible pairs SHALL be rejected before key sizing; otherwise identity key checks SHALL precede dependent alias checks. Choosing the pair SHALL NOT count its omitted namespace value as a decline. Retries SHALL NOT duplicate observations or leave speculative residency changes.

#### Scenario: A pair fails but its fallback succeeds

- **WHEN** the alias is blocked by key size or count capacity and namespace fallback is admitted
- **THEN** one matching alias decline is recorded, with no decline for the uncommitted identity value or successful fallback

#### Scenario: Both useful representations fail

- **WHEN** the identity key fails, preventing an alias attempt, and the fallback namespace key also fails
- **THEN** the identity-key and namespace-key declines are recorded once each, with no alias decline

### Requirement: Key sizing adds no warm-hit traversal

Key-size accounting SHALL occur only for prospective retention, reuse its result within one admission attempt including retries, and retain no additional key copy. Exact, compatible and alias warm hits SHALL NOT recursively traverse keys for sizing. Disabled key limits SHALL NOT allocate sizing state.

#### Scenario: A large predicate repeatedly hits

- **WHEN** repeated reads hit an already resident value or compatible source
- **THEN** no key-sizing pass is performed
