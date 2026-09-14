# cached-read-api Specification

## Purpose

This capability provides a narrow PyMongo-facing API for coherent process-local cached reads after the cache and change-stream foundations are healthy.

## Requirements

### Requirement: Sync and asyncio facades support the same cache contract

The library SHALL provide composed synchronous and native asyncio facades for supported collection reads. Neither facade SHALL close a caller-owned PyMongo client. Unsupported operations SHALL remain available through the raw collection.

#### Scenario: A caller closes a facade

- **WHEN** a caller closes a cached facade that wraps a caller-owned client
- **THEN** the facade releases its own resources without closing the caller-owned client

### Requirement: Only fully materialized supported reads are cached

The facades SHALL cache identity lookups and fully materialized bounded `find`, aggregation, count, estimated-count, and distinct results when the manager is healthy. They SHALL not admit partial, tailable, exhaust, oversize, session-bound, or otherwise unsupported reads. An aggregation pipeline containing a `$lookup`, `$unionWith`, or `$graphLookup` stage SHALL NOT be admitted, because its result depends on a namespace the cache cannot track invalidation for. An aggregation pipeline containing an `$out` or `$merge` stage SHALL NOT be admitted, because caching its result would skip that stage's write side effect on a later hit. An aggregation pipeline containing a `$sample` stage, an expression that executes caller-supplied JavaScript (`$function`, `$accumulator`), or a nondeterministic or time-dependent expression at any nesting depth (`$rand`, `$sampleRate`, `$$NOW`, `$$CLUSTER_TIME`) SHALL NOT be admitted, because its result can differ between executions with no collection write to invalidate the cached value against; `$function`/`$accumulator` are rejected unconditionally on presence, not by attempting to analyze their JavaScript body, since no static check can prove an opaque script deterministic. A `find`, `count_documents`, or `distinct` read whose filter contains `$where`, or an `$expr` embedding one of these same nondeterministic, time-dependent, or opaque-JavaScript expressions (including `$function`/`$accumulator`), SHALL NOT be admitted, for the same reasons. An aggregation pipeline containing a `$collStats`, `$indexStats`, or `$planCacheStats` stage SHALL NOT be admitted, because these stages report live collection, index, or query-plan statistics that change as operations execute, independent of any write the change-stream mechanism would invalidate against. `aggregate` SHALL reject a pipeline containing a `$changeStream` stage outright rather than execute it, because this facade always fully materializes an aggregation's result and a change-stream cursor has no natural end to materialize toward; a caller needing one SHALL use the raw collection. A read whose `_id` identity or generic-result discriminator contains a value that cannot be canonicalized into a cache key (for example, a BSON type such as `Code` that cannot be hashed, or a NaN value, which is never equal to itself) SHALL NOT be admitted; the facade SHALL execute the read and return its result unaffected rather than raise. A collection backed by a MongoDB view SHALL NOT have any of its reads admitted once the manager has processed the change-stream event establishing that the collection is view-backed. A facade SHALL re-verify whether a collection is view-backed whenever the namespace epoch it last checked against is stale, so a collection dropped and recreated as a view after being wrapped, or a namespace created as a view after being wrapped while absent, does not remain cache-eligible indefinitely. If that re-verification cannot determine the collection's type (for example, the caller is not authorized to run `listCollections`), the facade SHALL bypass the cache for that read without recording a determination, so the next read re-verifies again rather than treating an inconclusive check as a permanent view determination. As with every other invalidation in this system, this guarantee is scoped to after the triggering event is processed, not to the instant the underlying DDL runs on the server; a read racing ahead of event delivery may still observe the prior eligibility determination, consistent with the bounded/eventual coherency documented in `implement-change-stream-coherency`.

#### Scenario: A previously ordinary collection becomes a view

- **WHEN** a wrapped collection that was cache-eligible is dropped and recreated as a MongoDB view, and the manager has processed the resulting event advancing its namespace epoch
- **THEN** the facade re-verifies collection type before treating a subsequent read as cache-eligible and, finding it is now a view, bypasses cache lookup and admission for it

#### Scenario: A namespace wrapped while absent is created as a view

- **WHEN** a facade wraps a collection name that does not yet exist, that namespace is later created as a MongoDB view, and the manager has processed the resulting `create` event
- **THEN** the facade re-verifies collection type before treating a subsequent read as cache-eligible, using the epoch advance from that event, and bypasses cache lookup and admission for it

#### Scenario: A caller abandons a cursor

- **WHEN** a caller partially consumes a cacheable-looking cursor
- **THEN** the facade does not admit its incomplete result to the cache

#### Scenario: An aggregation pipeline reads a foreign collection

- **WHEN** a caller runs an aggregation pipeline containing a `$lookup`, `$unionWith`, or `$graphLookup` stage
- **THEN** the facade executes the pipeline and returns its result without admitting it to the cache

#### Scenario: An aggregation pipeline writes to a collection

- **WHEN** a caller runs an aggregation pipeline containing an `$out` or `$merge` stage
- **THEN** the facade executes the pipeline, including its write side effect, and returns its result without admitting it to the cache

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

#### Scenario: An aggregation pipeline requests a change stream

- **WHEN** a caller runs `aggregate` with a pipeline containing a `$changeStream` stage
- **THEN** the facade raises without executing the pipeline, rather than blocking indefinitely while fully materializing an unbounded cursor

#### Scenario: A read's identity or discriminator cannot be canonicalized

- **WHEN** a caller performs a supported read whose `_id` identity or generic-result discriminator contains a value that cannot be hashed (for example, a `bson.Code` value) or a value that is not equal to itself (a BSON NaN)
- **THEN** the facade executes the read and returns its result without a cache hit or admission, instead of raising

#### Scenario: A caller reads from a view

- **WHEN** a caller performs a supported read against a collection that is backed by a MongoDB view
- **THEN** the facade executes the read and returns its result without a cache hit or admission

#### Scenario: View inspection cannot determine the collection's type

- **WHEN** a facade's re-verification of a collection's type fails to get a conclusive answer (for example, the caller is not authorized to run `listCollections`)
- **THEN** the facade bypasses the cache for that read, and a later read re-verifies the collection's type again rather than reusing the inconclusive result

### Requirement: Cached reads retain database consistency boundaries

Cache-admitted reads SHALL use primary read preference and majority read concern. A caller-selected read preference other than primary or read concern other than majority SHALL bypass both cache lookup and admission, and the facade SHALL delegate that read without rewriting the caller's PyMongo read options. Session-bound reads and cache use during manager recovery SHALL bypass the cache. A read against a database whose change stream cannot be established at all (for example, because the server does not meet the minimum supported version) SHALL bypass the cache the same way, rather than raise, so an otherwise-supported read still returns a direct result. Returned values SHALL remain isolated from caller mutation.

#### Scenario: A session-bound read is requested

- **WHEN** a caller supplies a PyMongo session to a supported read
- **THEN** the facade delegates directly to PyMongo without a cache hit or admission

#### Scenario: A database's change stream cannot be established

- **WHEN** a caller performs a supported read against a database whose change stream fails to start
- **THEN** the facade executes the read and returns its result without a cache hit or admission, instead of raising

#### Scenario: A caller selects an incompatible read profile

- **WHEN** a caller configures the wrapped collection or read operation with a secondary or non-majority read profile
- **THEN** the facade delegates directly to PyMongo with that profile, without a cache hit or admission and without forcing primary or majority semantics

### Requirement: Unique keys are discovered from server index metadata, not declared

The facades SHALL discover unique keys for a namespace from `list_indexes()` rather than from a caller declaration. A discovered key SHALL be limited to indexes with `unique: true` that have no `partialFilterExpression`, are not `sparse`, and are not a hashed key, since only such an index unconditionally guarantees uniqueness for every document. A read SHALL only take the alias path through a discovered key when the read's effective collation exactly matches the index's collation. Discovery SHALL be re-performed whenever the namespace's index generation has advanced since the last check, and SHALL be shared across every facade handle for the same namespace. The index generation SHALL advance whenever the manager processes a `createIndexes` or `dropIndexes` change-stream event for that namespace, or whenever the namespace epoch itself advances (drop/recreate/create).

#### Scenario: A unique index is discovered and used

- **WHEN** a caller reads by an equality filter matching a unique, non-partial, non-sparse, non-hashed index's field set under the read's effective collation
- **THEN** the facade treats the read as a unique-key read eligible for alias-based identity caching

#### Scenario: A partial, sparse, or hashed unique index is not used

- **WHEN** a unique index has a `partialFilterExpression`, is `sparse`, or is hashed
- **THEN** the facade does not use it as a unique key, and a matching read is treated as a generic bounded read instead

#### Scenario: A read's collation does not match the index's collation

- **WHEN** a caller's read specifies a collation different from a unique index's collation (or specifies none while the index has a non-default collation)
- **THEN** the facade does not use that index as a unique key for the read, and the read is treated as a generic bounded read instead

#### Scenario: An index is added or removed on a live collection

- **WHEN** a unique index is created or dropped on a live collection without the collection being dropped and recreated, and the manager has processed the resulting `createIndexes`/`dropIndexes` event
- **THEN** the facade re-verifies discovery before treating a subsequent read as eligible for the alias path, reflecting the index change

### Requirement: Unresolved and negative unique-key reads are guarded conservatively

A unique-key read whose alias has not yet been resolved to a document identity SHALL capture only the namespace generation before the database read, since the document identity is unknown until the read responds, and SHALL admit a namespace-guarded entry keyed by the unique-key definition, value, and read shape. On a match, the facade SHALL resolve and record the alias for that key value; if the caller's own projection excludes `_id`, the facade SHALL still fetch `_id` from the server for resolution — by overriding `_id: 0` to `_id: 1` for an inclusion-style caller projection, or by omitting the caller's `_id: 0` for an exclusion-style one, never by adding `_id: 1` to an exclusion-style projection, which MongoDB rejects as a mixed inclusion/exclusion projection — and SHALL NOT expose `_id` in the returned or cached value. On a match, the facade SHALL also admit an identity-guarded entry for the same document and read shape, guarded by the document's current identity generation and the namespace epoch, in addition to the namespace-guarded entry; this is required because cache-core prunes an alias once no cached entry references the identity it resolves to, and a namespace-guarded entry carries no such reference, so an alias published without an accompanying identity-guarded entry would be pruned immediately and never actually route a later read to the identity-guarded path. On no match, the facade SHALL admit a negative result guarded by the captured namespace generation, not by a document identity generation. A subsequent read of a key value with a resolved alias SHALL capture that document's identity generation and the namespace epoch before the read and SHALL admit an identity-guarded entry keyed by that identity and the read's shape, not by the namespace generation.

#### Scenario: A unique-key value is looked up for the first time

- **WHEN** a caller reads by a unique key with no existing alias for that key value
- **THEN** the facade captures the namespace generation before the read, and admits the resulting match or negative result guarded by that namespace generation rather than an identity generation, keyed by the unique-key definition, value, and read shape

#### Scenario: A first-time match also admits an identity-guarded entry

- **WHEN** a caller reads by a unique key with no existing alias, and the read matches a document
- **THEN** the facade admits both the namespace-guarded entry for the unique-key value and an identity-guarded entry for the matched document, so the newly published alias has an identity-guarded entry keeping it alive and a subsequent read of the same key value takes the identity-guarded path immediately

#### Scenario: A resolved unique-key alias is read again

- **WHEN** a caller reads by a unique key whose alias was already resolved by an earlier read
- **THEN** the facade captures that document's identity generation and the namespace epoch before the read and admits an identity-guarded entry keyed by that identity and the read's shape

#### Scenario: A unique-key match excludes `_id` from its projection

- **WHEN** a caller reads by an unresolved unique key with a projection that excludes `_id`, and the read matches a document
- **THEN** the facade resolves and records the alias using the document's `_id` fetched from the server, and neither the value returned to the caller nor the value admitted to the cache includes `_id`

#### Scenario: A unique-key match uses an exclusion-style projection

- **WHEN** a caller reads by an unresolved unique key with an exclusion-style projection that excludes `_id` alongside another field (e.g. `{"_id": 0, "secret": 0}`)
- **THEN** the facade omits the caller's `_id: 0` from the server-side projection rather than adding `_id: 1`, since `_id` is included by default once its exclusion is omitted and adding `_id: 1` would make the projection invalid

### Requirement: A resolved unique-key read re-verifies against its original predicate on a cache miss

A read of a key value with a resolved alias SHALL first attempt a cache lookup keyed by the resolved identity and the read's shape. On a cache miss, the facade SHALL query the database by the caller's original unique-key predicate (field and value), and SHALL NOT query by the resolved identity alone, because a write to the resolved document could have changed the field the alias was resolved from, or, after the namespace was dropped and recreated, the same identity value could now belong to an unrelated document. The facade SHALL compare the identity of the response (or its absence) against the identity the alias recorded. When they agree, the facade SHALL capture the document's current identity generation and admit or refresh the identity-guarded entry. When they disagree — a different document matched, or none did — the facade SHALL treat the alias as stale, discard or re-resolve it, and admit the result the same way an unresolved unique-key read would.

#### Scenario: A resolved alias is still accurate

- **WHEN** a cache miss occurs for a key value with a resolved alias, and a database query by the original predicate matches the same document identity the alias recorded
- **THEN** the facade admits or refreshes the identity-guarded entry for that document, confirming the alias remains valid

#### Scenario: A resolved alias has gone stale

- **WHEN** a cache miss occurs for a key value with a resolved alias, and a database query by the original predicate matches a different document identity than the alias recorded, or matches no document at all
- **THEN** the facade does not return or cache a value based on the stale alias's identity; it discards or re-resolves the alias and admits the result according to the query's actual outcome
