## Purpose

This capability provides a narrow PyMongo-facing API for coherent process-local cached reads after the cache and change-stream foundations are healthy.

## ADDED Requirements

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
