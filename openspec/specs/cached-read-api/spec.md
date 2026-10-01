# cached-read-api Specification

## Purpose

This capability provides a narrow PyMongo-facing API for coherent process-local cached reads after the cache and change-stream foundations are healthy.

## Requirements

### Requirement: Sync and asyncio views expose cache-aware reads

Synchronous and asyncio facades SHALL support the same cache-aware read contract. Cached database and collection views SHALL expose indexed and attribute-style access to cache-aware collection views, without handing back an uncached PyMongo collection by accident.

#### Scenario: Attribute-style collection access stays cache-aware

- **WHEN** a caller accesses a collection by attribute on a `CachedDatabase` or a sub-collection by attribute on a `CachedCollection` (for example `database.users` or `collection.chunks`), rather than by `[name]`
- **THEN** the facade returns a `CachedCollection` for it, the same as `database["users"]` or `collection["chunks"]` would, not the raw PyMongo `Collection` that attribute access would otherwise return

#### Scenario: A caller changes collection options

- **WHEN** a caller obtains a PyMongo collection with `get_collection(...)` or `with_options(...)` and requests its cached read view
- **THEN** the view retains that optioned collection as `.raw` and applies its effective options to cache eligibility and direct reads

### Requirement: A cached read view accepts an existing PyMongo collection

The synchronous and asyncio managers SHALL provide a typed cached read view for a caller-supplied PyMongo collection belonging to that manager's client. The view SHALL retain that exact collection as `.raw`, including its configured options. A collection belonging to another client SHALL be rejected rather than silently watched through the wrong client.

#### Scenario: A caller uses one collection for writes and cached reads

- **WHEN** a caller obtains a PyMongo collection from the manager's client and requests its cached read view
- **THEN** direct calls on the PyMongo collection retain PyMongo's declared methods and return types, and the view's six supported read methods use that collection's options and the manager's cache

#### Scenario: A caller supplies another client's collection

- **WHEN** a caller requests a cached read view for a collection owned by a different client
- **THEN** the manager rejects the request before starting a change stream or performing a read

#### Scenario: A caller requests the same collection more than once

- **WHEN** a caller requests multiple cached read views for a collection from one cache manager
- **THEN** the views share that manager's cache entries and database change-stream supervisor, so a read through one view can hit an entry admitted through another
- **AND** callers are not promised that the views are the same Python object

### Requirement: Ordinary PyMongo operations retain native tooling

Cached database and collection views SHALL expose their own cache-aware reads and collection traversal, but SHALL NOT present arbitrary PyMongo methods as view methods. Ordinary PyMongo operations SHALL remain available on the caller-owned PyMongo object and through `.raw`, with PyMongo's own signatures and return types visible to static analysis and source navigation.

#### Scenario: A caller invokes a PyMongo write or administration method

- **WHEN** a caller needs `insert_one`, `drop`, `create_index`, `create_collection`, or another operation outside the cached view's declared surface
- **THEN** the caller can invoke it on the original PyMongo collection or database, or on the view's `.raw` object, and source navigation resolves to PyMongo's declared method
- **AND** the cached view does not expose that operation through an untyped delegation method

### Requirement: Facades preserve caller-owned clients

Closing a cached facade SHALL leave its caller-owned PyMongo client open.

#### Scenario: A caller closes a facade

- **WHEN** a caller closes a cached facade that wraps a caller-owned client
- **THEN** the facade releases its own resources without closing the caller-owned client

### Requirement: Raw access exposes overridden PyMongo methods

The `.raw` property SHALL expose the exact wrapped PyMongo object for calls requiring PyMongo semantics, including calls whose names are overridden by cache-aware reads.

#### Scenario: A caller needs PyMongo's own semantics for an overridden method name

- **WHEN** a caller needs PyMongo's own behavior for `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, or `distinct` (for example, a tailable or exhaust cursor, or a `$changeStream` pipeline) that the facade's cache-aware override of that method name cannot provide
- **THEN** the caller reaches the wrapped PyMongo object through `.raw` and calls the method there, bypassing the facade's override entirely

### Requirement: Incomplete results are not admitted

The facades SHALL admit only complete, bounded results of supported reads.

#### Scenario: A caller abandons a cursor

- **WHEN** a caller partially consumes a cacheable-looking cursor
- **THEN** the facade does not admit its incomplete result to the cache

### Requirement: Cross-collection aggregation bypasses caching

Aggregation results that depend on another collection SHALL bypass cache admission.

#### Scenario: An aggregation pipeline reads a foreign collection

- **WHEN** a caller runs an aggregation pipeline containing a `$lookup`, `$unionWith`, or `$graphLookup` stage
- **THEN** the facade executes the pipeline and returns its result without admitting it to the cache

### Requirement: Aggregation writes are never skipped by a cache hit

Aggregation pipelines with write stages SHALL bypass cache admission.

#### Scenario: An aggregation pipeline writes to a collection

- **WHEN** a caller runs an aggregation pipeline containing an `$out` or `$merge` stage
- **THEN** the facade executes the pipeline, including its write side effect, and returns its result without admitting it to the cache

### Requirement: Variable or live data bypasses caching

Reads whose results can change without a collection write SHALL bypass cache admission.

#### Scenario: An aggregation pipeline is nondeterministic

- **WHEN** a caller runs an aggregation pipeline containing a `$sample` stage or a `$rand`/`$sampleRate` expression
- **THEN** the facade executes the pipeline and returns its result without admitting it to the cache, so a later call is not frozen to the first random result

#### Scenario: An aggregation pipeline is time-dependent

- **WHEN** a caller runs an aggregation pipeline using the `$$NOW` or `$$CLUSTER_TIME` system variable
- **THEN** the facade executes the pipeline and returns its result without admitting it to the cache, so a later call is not frozen to the first computed timestamp

#### Scenario: A plain filter is nondeterministic

- **WHEN** a caller runs a `find_one`, `find`, `count_documents`, or `distinct` read whose filter contains `$where`, or an `$expr` embedding `$rand`, `$sampleRate`, `$$NOW`, or `$$CLUSTER_TIME`
- **THEN** the facade executes the read and returns its result without admitting it to the cache, so a later call is not frozen to the first result

#### Scenario: An aggregation pipeline executes caller-supplied JavaScript

- **WHEN** a caller runs an aggregation pipeline containing a `$function` or `$accumulator` expression
- **THEN** the facade executes the pipeline and returns its result without admitting it to the cache, regardless of what the JavaScript body does

#### Scenario: An aggregation pipeline reports live statistics

- **WHEN** a caller runs an aggregation pipeline containing a `$collStats`, `$indexStats`, or `$planCacheStats` stage
- **THEN** the facade executes the pipeline and returns its result without admitting it to the cache, so a later call is not frozen to statistics captured at the first execution

#### Scenario: A plain filter executes caller-supplied JavaScript

- **WHEN** a caller runs a `find_one`, `find`, `count_documents`, or `distinct` read whose filter contains an `$expr` embedding `$function` or `$accumulator`
- **THEN** the facade executes the read and returns its result without admitting it to the cache, regardless of what the JavaScript body does

### Requirement: Change-stream aggregation is rejected

The cache-aware `aggregate` method SHALL reject `$changeStream` pipelines.

#### Scenario: An aggregation pipeline requests a change stream

- **WHEN** a caller runs `aggregate` with a pipeline containing a `$changeStream` stage
- **THEN** the facade raises without executing the pipeline, rather than blocking indefinitely while fully materializing an unbounded cursor

### Requirement: Uncanonicalizable keys bypass caching

Reads whose identity or result discriminator cannot be canonicalized SHALL execute without cache admission.

#### Scenario: A read's identity or discriminator cannot be canonicalized

- **WHEN** a caller performs a supported read whose `_id` identity or generic-result discriminator contains a value that cannot be hashed (for example, a `bson.Code` value) or a value that is not equal to itself (a BSON NaN)
- **THEN** the facade executes the read and returns its result without a cache hit or admission, instead of raising

### Requirement: Only confirmed ordinary collections are cache eligible

The facades SHALL use cache lookup and admission only for confirmed ordinary MongoDB collections.

#### Scenario: A caller reads from a view

- **WHEN** a caller performs a supported read against a collection that is backed by a MongoDB view
- **THEN** the facade executes the read and returns its result without a cache hit or admission

#### Scenario: Time-series reads always reach MongoDB

- **WHEN** a caller repeats any supported read method on a time-series collection while the database stream is healthy
- **THEN** each call executes against MongoDB without a cache hit or admission, preserving options, return shape, and database errors
- **AND** successful calls increment bypass statistics rather than hit statistics

#### Scenario: An independent writer changes time-series data

- **WHEN** an independent client inserts a measurement after an earlier facade read and the insert is visible to an equivalent direct read
- **THEN** a subsequent facade read observes the database result without waiting for a time-series invalidation event

### Requirement: Collection eligibility is rechecked after namespace changes

The facades SHALL recheck collection type after a namespace epoch change and retry inconclusive probes on later reads.

#### Scenario: A previously ordinary collection becomes a view

- **WHEN** a wrapped collection that was cache-eligible is dropped and recreated as a MongoDB view, and the manager has processed the resulting event advancing its namespace epoch
- **THEN** the facade re-verifies collection type before treating a subsequent read as cache-eligible and, finding it is now a view, bypasses cache lookup and admission for it

#### Scenario: A namespace wrapped while absent is created as a view

- **WHEN** a facade wraps a collection name that does not yet exist, that namespace is later created as a MongoDB view, and the manager has processed the resulting `create` event
- **THEN** the facade re-verifies collection type before treating a subsequent read as cache-eligible, using the epoch advance from that event, and bypasses cache lookup and admission for it

#### Scenario: View inspection cannot determine the collection's type

- **WHEN** a facade's re-verification of a collection's type fails to get a conclusive answer (for example, the caller is not authorized to run `listCollections`)
- **THEN** the facade bypasses the cache for that read, and a later read re-verifies the collection's type again rather than reusing the inconclusive result

#### Scenario: An ordinary collection is replaced by time-series

- **WHEN** a cached ordinary collection is dropped, the manager processes its drop event, and the name is recreated as time-series
- **THEN** subsequent reads recheck collection type and bypass cache lookup and admission

#### Scenario: An absent name later becomes time-series

- **WHEN** a facade reads an absent namespace, and that name is subsequently created as a time-series collection
- **THEN** the absent read's result is not cached and later reads recheck the type and bypass, without relying on a time-series creation event

#### Scenario: An absent name later becomes an ordinary collection

- **WHEN** a facade reads an absent namespace and that name is later created as an ordinary collection
- **THEN** subsequent reads recheck the type and can cache eligible results, including missing-document results in the existing collection

### Requirement: Cache reads honor the supported consistency profile

Cache-admitted reads SHALL use primary read preference and majority read concern; incompatible caller profiles SHALL bypass caching.

#### Scenario: A caller selects an incompatible read profile

- **WHEN** a caller configures the wrapped collection or read operation with a secondary or non-majority read profile
- **THEN** the facade delegates directly to PyMongo with that profile, without a cache hit or admission and without forcing primary or majority semantics

### Requirement: Session-bound reads bypass caching

Session-bound reads SHALL bypass cache lookup and admission.

#### Scenario: A session-bound read is requested

- **WHEN** a caller supplies a PyMongo session to a supported read
- **THEN** the facade delegates directly to PyMongo without a cache hit or admission

### Requirement: Unestablished streams bypass caching

Reads SHALL bypass caching when the database change stream cannot be established.

#### Scenario: A database's change stream cannot be established

- **WHEN** a caller performs a supported read against a database whose change stream fails to start
- **THEN** the facade executes the read and returns its result without a cache hit or admission, instead of raising

### Requirement: Unique-key eligibility follows index metadata

The facades SHALL use only unconditional unique indexes with locally confirmed matching effective collation for unique-key aliases. A single-document read's effective collation SHALL include a supported explicit override or the collection's default when no override is supplied. An explicit collation whose omitted locale-specific defaults prevent locally confirming equivalence SHALL use generic namespace caching. A deterministic mapping predicate, including a regex-ID query, that does not qualify for a unique-key alias SHALL use the generic namespace-guarded path when its remaining eligibility conditions are satisfied.

#### Scenario: A unique index is discovered and used

- **WHEN** a caller reads by an equality filter matching a unique, non-partial, non-sparse, non-hashed index's field set under the read's effective collation
- **THEN** the facade treats the read as a unique-key read eligible for alias-based identity caching

#### Scenario: A partial, sparse, or hashed unique index is not used

- **WHEN** a unique index has a `partialFilterExpression`, is `sparse`, or is hashed
- **THEN** the facade does not use it as a unique key, and a matching read is treated as a generic bounded read instead

#### Scenario: A read's collation does not match the index's collation

- **WHEN** a caller's read has an effective collation different from a unique index's collation, whether explicitly selected or inherited from the collection default
- **THEN** the facade does not use that index as a unique key for the read, and the read is treated as a generic bounded read instead

#### Scenario: An inherited collation matches a unique index

- **WHEN** a caller omits per-query collation, the collection default matches a qualifying unique index's non-default collation, and the equality predicate matches its complete key definition
- **THEN** the facade can use the unique-key path under the inherited effective collation rather than disqualifying the index because the option was omitted

#### Scenario: An explicit collation matches a unique index

- **WHEN** a fully specified supported explicit read collation matches a qualifying unique index and the equality predicate matches its complete key definition
- **THEN** the facade can use the unique-key path under that effective collation without reusing an alias from different collation semantics

#### Scenario: Explicit collation equivalence cannot be confirmed locally

- **WHEN** an explicit read collation omits locale-specific defaults required to confirm equality with expanded index metadata
- **THEN** the read uses generic namespace caching rather than assuming equivalent collation semantics or performing another database operation to resolve defaults

### Requirement: Unique-key metadata refreshes after index changes

The facades SHALL rediscover unique keys after the manager observes an index or namespace generation change.

#### Scenario: An index is added or removed on a live collection

- **WHEN** a unique index is created or dropped on a live collection without the collection being dropped and recreated, and the manager has processed the resulting `createIndexes`/`dropIndexes` event
- **THEN** the facade re-verifies discovery before treating a subsequent read as eligible for the alias path, reflecting the index change

### Requirement: Unresolved unique-key reads use namespace guards

A unique-key read without a resolved alias SHALL use namespace generation protection.

#### Scenario: A unique-key value is looked up for the first time

- **WHEN** a caller reads by a unique key with no existing alias for that key value
- **THEN** the facade captures the namespace generation before the read, and admits the resulting match or negative result guarded by that namespace generation rather than an identity generation, keyed by the unique-key definition, value, and read shape

### Requirement: First unique-key matches admit an identity entry

A first-time unique-key match SHALL also admit an identity-guarded entry when eligible.

#### Scenario: A first-time match also admits an identity-guarded entry

- **WHEN** a caller reads by a unique key with no existing alias, and the read matches a document
- **THEN** the facade admits both the namespace-guarded entry for the unique-key value and an identity-guarded entry for the matched document, so the newly published alias has an identity-guarded entry keeping it alive and a subsequent read of the same key value takes the identity-guarded path immediately

#### Scenario: A resolved unique-key alias is read again

- **WHEN** a caller reads by a unique key whose alias was already resolved by an earlier read
- **THEN** the facade captures that document's identity generation and the namespace epoch before the read and admits an identity-guarded entry keyed by that identity and the read's shape

### Requirement: Unique-key resolution obtains identity despite projection

The facade SHALL resolve document identity for unique-key aliases even when the caller excludes `_id`.

#### Scenario: A unique-key match excludes `_id` from its projection

- **WHEN** a caller reads by an unresolved unique key with a projection that excludes `_id`, and the read matches a document
- **THEN** the facade resolves and records the alias using the document's `_id` fetched from the server, and neither the value returned to the caller nor the value admitted to the cache includes `_id`

#### Scenario: A unique-key match uses an exclusion-style projection

- **WHEN** a caller reads by an unresolved unique key with an exclusion-style projection that excludes `_id` alongside another field (e.g. `{"_id": 0, "secret": 0}`)
- **THEN** the facade omits the caller's `_id: 0` from the server-side projection rather than adding `_id: 1`, since `_id` is included by default once its exclusion is omitted and adding `_id: 1` would make the projection invalid

### Requirement: Resolved aliases are reverified on cache misses

A resolved unique-key read SHALL verify its original predicate against MongoDB on an identity cache miss.

#### Scenario: A resolved alias is still accurate

- **WHEN** a cache miss occurs for a key value with a resolved alias, and a database query by the original predicate matches the same document identity the alias recorded
- **THEN** the facade admits or refreshes the identity-guarded entry for that document, confirming the alias remains valid

#### Scenario: A resolved alias has gone stale

- **WHEN** a cache miss occurs for a key value with a resolved alias, and a database query by the original predicate matches a different document identity than the alias recorded, or matches no document at all
- **THEN** the facade does not return or cache a value based on the stale alias's identity; it discards or re-resolves the alias and admits the result according to the query's actual outcome

### Requirement: Generic single-document reads use namespace caching

Synchronous and asyncio cached single-document reads SHALL cache deterministic mapping filters that do not qualify for an exact identity or unique-key optimization, including compound predicates and match-all reads. Their entries SHALL be guarded against writes anywhere in the queried collection and against namespace or stream-continuity changes. Negative results SHALL be cacheable under the same guard. Unsafe filters or projections, session-bound reads, unsupported options, uncanonicalizable inputs, incompatible read profiles, and ineligible collections or streams SHALL retain direct execution with the original arguments and errors.

#### Scenario: A caller repeats a compound predicate

- **WHEN** a caller repeats an eligible single-document query with an `_id` equality and an additional predicate
- **THEN** the repeated query can hit a namespace-guarded entry without ignoring the additional predicate

#### Scenario: A matching document changes

- **WHEN** a generic result is cached and the manager processes a write affecting which document satisfies the query
- **THEN** the next read cannot return the pre-invalidation cached result

#### Scenario: A negative generic result gains a match

- **WHEN** a generic query cached a missing result and the manager processes an insert or update that creates a match
- **THEN** the next read fetches the current database result rather than the cached negative result

#### Scenario: A write touches another document

- **WHEN** a write to a different document in the same collection is processed after generic admission
- **THEN** the generic result is invalidated conservatively, while unrelated exact-identity entries retain their existing narrower guards

#### Scenario: Index metadata is unavailable

- **WHEN** collection type and stream continuity are confirmed but unique-index discovery is inconclusive
- **THEN** an otherwise eligible deterministic mapping query can use the generic namespace path without assuming uniqueness

#### Scenario: Unsafe query input follows a cached safe query

- **WHEN** a caller supplies a nondeterministic or otherwise unsafe filter or projection
- **THEN** the read executes through the original database operation without a hit or admission, even if another safe query was previously cached

### Requirement: Single-document sort and collation are explicit

Both execution models SHALL expose explicit keyword-only sorting and collation options on cached single-document reads. Generic cache keys SHALL distinguish every output-affecting predicate, projection, ordered sort specification, effective collation, and decoding profile. Valid equivalent default forms SHALL have consistent matching semantics. Cached results SHALL preserve the database's single-document return shape and SHALL NOT promise ordering beyond that of the corresponding database operation. A malformed or unsupported option SHALL NOT hit a previously valid entry or mask the database driver's error.

#### Scenario: Sorting selects a different document

- **WHEN** two otherwise identical generic queries use different sorts that select different first documents
- **THEN** each query returns and caches its own corresponding result

#### Scenario: Collation changes matching

- **WHEN** two queries differ in effective collation and that difference changes which strings match
- **THEN** the queries cannot reuse a result admitted under incompatible matching semantics

#### Scenario: Effective collation affects an identity predicate

- **WHEN** a non-simple effective collation makes an `_id` predicate match a different set of values than its exact-identity optimization assumes
- **THEN** the read uses a generic namespace guard rather than an unsound identity alias

#### Scenario: Omitted collation inherits a non-simple default

- **WHEN** a caller omits collation on a collection with a non-simple default and issues a string `_id` predicate or scalar-ID shorthand
- **THEN** matching uses the collection default and namespace invalidation protects a result whose stored identity differs from the query's spelling

#### Scenario: Explicit simple collation overrides the default

- **WHEN** a caller requests simple collation for an exact `_id` lookup on a collection with a non-simple default
- **THEN** the read can retain its exact-identity optimization without sharing a result from the inherited non-simple matching semantics

#### Scenario: Sorting affects projected metadata

- **WHEN** two single-document reads select the same identity but different valid sorts affect their projected metadata
- **THEN** cache hits preserve each read's corresponding projected output rather than sharing a result solely because the selected document is unique

#### Scenario: A malformed option follows a warm entry

- **WHEN** a caller repeats a warm query with a malformed sort or collation argument
- **THEN** the malformed request does not return the warm result and preserves the appropriate driver error

#### Scenario: An unsupported extra option is supplied

- **WHEN** a caller supplies an option outside the explicitly supported cache contract
- **THEN** the original single-document operation executes directly with that option rather than silently discarding it
