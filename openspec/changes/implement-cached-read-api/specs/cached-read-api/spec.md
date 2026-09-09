## Purpose

This capability provides a narrow PyMongo-facing API for coherent process-local cached reads after the cache and change-stream foundations are healthy.

## ADDED Requirements

### Requirement: Sync and asyncio facades support the same cache contract

The library SHALL provide composed synchronous and native asyncio facades for supported collection reads. Neither facade SHALL close a caller-owned PyMongo client. Unsupported operations SHALL remain available through the raw collection.

#### Scenario: A caller closes a facade

- **WHEN** a caller closes a cached facade that wraps a caller-owned client
- **THEN** the facade releases its own resources without closing the caller-owned client

### Requirement: Only fully materialized supported reads are cached

The facades SHALL cache identity lookups and fully materialized bounded `find`, aggregation, count, estimated-count, and distinct results when the manager is healthy. They SHALL not admit partial, tailable, exhaust, oversize, session-bound, or otherwise unsupported reads. An aggregation pipeline containing a `$lookup`, `$unionWith`, or `$graphLookup` stage SHALL NOT be admitted, because its result depends on a namespace the cache cannot track invalidation for. An aggregation pipeline containing an `$out` or `$merge` stage SHALL NOT be admitted, because caching its result would skip that stage's write side effect on a later hit. An aggregation pipeline containing a `$sample` stage or a nondeterministic or time-dependent expression at any nesting depth (`$rand`, `$$NOW`, `$$CLUSTER_TIME`) SHALL NOT be admitted, because its result can differ between executions with no collection write to invalidate the cached value against. A collection backed by a MongoDB view SHALL NOT have any of its reads admitted once the manager has processed the change-stream event establishing that the collection is view-backed. A facade SHALL re-verify whether a collection is view-backed whenever the namespace epoch it last checked against is stale, so a collection dropped and recreated as a view after being wrapped, or a namespace created as a view after being wrapped while absent, does not remain cache-eligible indefinitely. As with every other invalidation in this system, this guarantee is scoped to after the triggering event is processed, not to the instant the underlying DDL runs on the server; a read racing ahead of event delivery may still observe the prior eligibility determination, consistent with the bounded/eventual coherency documented in `implement-change-stream-coherency`.

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

- **WHEN** a caller runs an aggregation pipeline containing a `$sample` stage or a `$rand` expression
- **THEN** the facade executes the pipeline and returns its result without admitting it to the cache, so a later call is not frozen to the first random result

#### Scenario: An aggregation pipeline is time-dependent

- **WHEN** a caller runs an aggregation pipeline using the `$$NOW` or `$$CLUSTER_TIME` system variable
- **THEN** the facade executes the pipeline and returns its result without admitting it to the cache, so a later call is not frozen to the first computed timestamp

#### Scenario: A caller reads from a view

- **WHEN** a caller performs a supported read against a collection that is backed by a MongoDB view
- **THEN** the facade executes the read and returns its result without a cache hit or admission

### Requirement: Unresolved and negative unique-key reads are guarded conservatively

A unique-key read whose alias has not yet been resolved to a document identity SHALL capture only the namespace generation before the database read, since the document identity is unknown until the read responds, and SHALL admit a namespace-guarded entry keyed by the unique-key definition, value, and read shape. On a match, the facade SHALL resolve and record the alias for that key value; if the caller's own projection excludes `_id`, the facade SHALL still fetch `_id` from the server for resolution — by overriding `_id: 0` to `_id: 1` for an inclusion-style caller projection, or by omitting the caller's `_id: 0` for an exclusion-style one, never by adding `_id: 1` to an exclusion-style projection, which MongoDB rejects as a mixed inclusion/exclusion projection — and SHALL NOT expose `_id` in the returned or cached value. On no match, the facade SHALL admit a negative result guarded by the captured namespace generation, not by a document identity generation. A subsequent read of a key value with a resolved alias, and every `_id` read, SHALL capture that document's identity generation and the namespace epoch before the read and SHALL admit an identity-guarded entry keyed by that identity and the read's shape, not by the namespace generation.

#### Scenario: A unique-key value is looked up for the first time

- **WHEN** a caller reads by a unique key with no existing alias for that key value
- **THEN** the facade captures the namespace generation before the read, and admits the resulting match or negative result guarded by that namespace generation rather than an identity generation, keyed by the unique-key definition, value, and read shape

#### Scenario: A resolved unique-key alias is read again

- **WHEN** a caller reads by a unique key whose alias was already resolved by an earlier read
- **THEN** the facade captures that document's identity generation and the namespace epoch before the read, the same as an `_id` read, and admits an identity-guarded entry keyed by that identity and the read's shape

#### Scenario: A unique-key match excludes `_id` from its projection

- **WHEN** a caller reads by an unresolved unique key with a projection that excludes `_id`, and the read matches a document
- **THEN** the facade resolves and records the alias using the document's `_id` fetched from the server, and neither the value returned to the caller nor the value admitted to the cache includes `_id`

#### Scenario: A unique-key match uses an exclusion-style projection

- **WHEN** a caller reads by an unresolved unique key with an exclusion-style projection that excludes `_id` alongside another field (e.g. `{"_id": 0, "secret": 0}`)
- **THEN** the facade omits the caller's `_id: 0` from the server-side projection rather than adding `_id: 1`, since `_id` is included by default once its exclusion is omitted and adding `_id: 1` would make the projection invalid

### Requirement: Cached reads retain database consistency boundaries

Cache-admitted reads SHALL use primary read preference and majority read concern. A caller-selected read preference other than primary or read concern other than majority SHALL bypass both cache lookup and admission, and the facade SHALL delegate that read without rewriting the caller's PyMongo read options. Session-bound reads and cache use during manager recovery SHALL bypass the cache. Returned values SHALL remain isolated from caller mutation.

#### Scenario: A session-bound read is requested

- **WHEN** a caller supplies a PyMongo session to a supported read
- **THEN** the facade delegates directly to PyMongo without a cache hit or admission

#### Scenario: A caller selects an incompatible read profile

- **WHEN** a caller configures the wrapped collection or read operation with a secondary or non-majority read profile
- **THEN** the facade delegates directly to PyMongo with that profile, without a cache hit or admission and without forcing primary or majority semantics
