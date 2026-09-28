# cached-read-api Specification

## Purpose

This capability provides a narrow PyMongo-facing API for coherent process-local cached reads after the cache and change-stream foundations are healthy.

## Requirements

### Requirement: Sync and asyncio facades expose cache-aware reads

Synchronous and asyncio facades SHALL support the same cache-aware read contract.

#### Scenario: Attribute-style collection access stays cache-aware

- **WHEN** a caller accesses a collection by attribute on a `CachedDatabase` or a sub-collection by attribute on a `CachedCollection` (PyMongo's own dot-access idiom, for example `database.users` or `collection.chunks`), rather than by `[name]`
- **THEN** the facade returns a `CachedCollection` for it, the same as `database["users"]` or `collection["chunks"]` would, not the raw PyMongo `Collection` that attribute access would otherwise return

#### Scenario: A delegated method that returns a new Collection or Database stays cache-aware

- **WHEN** a caller calls a delegated method whose return value is itself a PyMongo `Collection` or `Database` (for example `database.get_collection(name)`, `database.with_options(...)`, or `collection.with_options(...)`)
- **THEN** the facade wraps that returned object in a `CachedCollection`/`CachedDatabase` before returning it, rather than handing back the raw PyMongo object

### Requirement: Facades preserve caller-owned clients

Closing a cached facade SHALL leave its caller-owned PyMongo client open.

#### Scenario: A caller closes a facade

- **WHEN** a caller closes a cached facade that wraps a caller-owned client
- **THEN** the facade releases its own resources without closing the caller-owned client

### Requirement: Facades delegate methods they do not override

Facade methods not overridden for caching SHALL delegate unchanged to PyMongo.

#### Scenario: A caller invokes a method the facade does not override

- **WHEN** a caller calls a `CachedCollection` or `CachedDatabase` method that the facade does not itself define (for example `insert_one`, `update_one`, `create_index`, or `create_collection`)
- **THEN** the facade delegates the call, with its arguments, unmodified to the wrapped PyMongo `Collection` or `Database` and returns its result, without the caller needing `.raw`

### Requirement: Raw access exposes overridden PyMongo methods

The `.raw` property SHALL expose the wrapped PyMongo object for calls requiring PyMongo semantics.

#### Scenario: A caller needs PyMongo's own semantics for an overridden method name

- **WHEN** a caller needs PyMongo's own behavior for `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, or `distinct` (for example a tailable or exhaust cursor, or a `$changeStream` pipeline) that the facade's cache-aware override of that name rejects or cannot provide
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

- **WHEN** a caller runs a `find`, `count_documents`, or `distinct` read whose filter contains `$where`, or an `$expr` embedding `$rand`, `$sampleRate`, `$$NOW`, or `$$CLUSTER_TIME`
- **THEN** the facade executes the read and returns its result without admitting it to the cache, so a later call is not frozen to the first result

#### Scenario: An aggregation pipeline executes caller-supplied JavaScript

- **WHEN** a caller runs an aggregation pipeline containing a `$function` or `$accumulator` expression
- **THEN** the facade executes the pipeline and returns its result without admitting it to the cache, regardless of what the JavaScript body does

#### Scenario: An aggregation pipeline reports live statistics

- **WHEN** a caller runs an aggregation pipeline containing a `$collStats`, `$indexStats`, or `$planCacheStats` stage
- **THEN** the facade executes the pipeline and returns its result without admitting it to the cache, so a later call is not frozen to statistics captured at the first execution

#### Scenario: A plain filter executes caller-supplied JavaScript

- **WHEN** a caller runs a `find`, `count_documents`, or `distinct` read whose filter contains an `$expr` embedding `$function` or `$accumulator`
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

The facades SHALL use only unconditional unique indexes with matching effective collation for unique-key aliases.

#### Scenario: A unique index is discovered and used

- **WHEN** a caller reads by an equality filter matching a unique, non-partial, non-sparse, non-hashed index's field set under the read's effective collation
- **THEN** the facade treats the read as a unique-key read eligible for alias-based identity caching

#### Scenario: A partial, sparse, or hashed unique index is not used

- **WHEN** a unique index has a `partialFilterExpression`, is `sparse`, or is hashed
- **THEN** the facade does not use it as a unique key, and a matching read is treated as a generic bounded read instead

#### Scenario: A read's collation does not match the index's collation

- **WHEN** a caller's read specifies a collation different from a unique index's collation (or specifies none while the index has a non-default collation)
- **THEN** the facade does not use that index as a unique key for the read, and the read is treated as a generic bounded read instead

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
