# Spec Delta

## MODIFIED Requirements

### Requirement: Only fully materialized supported reads are cached

The facades SHALL cache identity lookups and fully materialized bounded `find`, aggregation, count, estimated-count, and distinct results when the manager is healthy. They SHALL not admit partial, tailable, exhaust, oversize, session-bound, or otherwise unsupported reads. An aggregation pipeline containing a `$lookup`, `$unionWith`, or `$graphLookup` stage SHALL NOT be admitted, because its result depends on a namespace the cache cannot track invalidation for. An aggregation pipeline containing an `$out` or `$merge` stage SHALL NOT be admitted, because caching its result would skip that stage's write side effect on a later hit. An aggregation pipeline containing a `$sample` stage, an expression that executes caller-supplied JavaScript (`$function`, `$accumulator`), or a nondeterministic or time-dependent expression at any nesting depth (`$rand`, `$sampleRate`, `$$NOW`, `$$CLUSTER_TIME`) SHALL NOT be admitted, because its result can differ between executions with no collection write to invalidate the cached value against; `$function`/`$accumulator` are rejected unconditionally on presence, not by attempting to analyze their JavaScript body, since no static check can prove an opaque script deterministic. A `find`, `count_documents`, or `distinct` read whose filter contains `$where`, or an `$expr` embedding one of these same nondeterministic, time-dependent, or opaque-JavaScript expressions (including `$function`/`$accumulator`), SHALL NOT be admitted, for the same reasons. An aggregation pipeline containing a `$collStats`, `$indexStats`, or `$planCacheStats` stage SHALL NOT be admitted, because these stages report live collection, index, or query-plan statistics that change as operations execute, independent of any write the change-stream mechanism would invalidate against. `aggregate` SHALL reject a pipeline containing a `$changeStream` stage outright rather than execute it, because this facade always fully materializes an aggregation's result and a change-stream cursor has no natural end to materialize toward; a caller needing one SHALL use the raw collection. A read whose `_id` identity or generic-result discriminator contains a value that cannot be canonicalized into a cache key (for example, a BSON type such as `Code` that cannot be hashed, or a NaN value, which is never equal to itself) SHALL NOT be admitted; the facade SHALL execute the read and return its result unaffected rather than raise. A collection backed by a MongoDB view SHALL NOT have any of its reads admitted once the manager has processed the change-stream event establishing that the collection is view-backed. A facade SHALL re-verify whether a collection is view-backed whenever the namespace epoch it last checked against is stale, so a collection dropped and recreated as a view after being wrapped, or a namespace created as a view after being wrapped while absent, does not remain cache-eligible indefinitely. If that re-verification cannot determine the collection's type (for example, the caller is not authorized to run `listCollections`), the facade SHALL bypass the cache for that read without recording a determination, so the next read re-verifies again rather than treating an inconclusive check as a permanent view determination. As with every other invalidation in this system, this guarantee is scoped to after the triggering event is processed, not to the instant the underlying DDL runs on the server; a read racing ahead of event delivery may still observe the prior eligibility determination, consistent with the bounded/eventual coherency documented in `implement-change-stream-coherency`.

Both synchronous and asyncio facades SHALL require a confirmed ordinary collection (`type: collection`) before cache lookup or admission. Time-series collections (`type: timeseries`) and views SHALL bypass both lookup and admission for all supported read methods: `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, and `distinct`. Bypassed reads SHALL retain the facade's return shape and existing validation while delegating with the caller's PyMongo options and propagating database errors. Successful bypasses SHALL be counted as bypasses, not hits.

An absent namespace or an inconclusive collection-type probe SHALL bypass lookup and admission, including negative or empty results, without memoizing an eligibility determination; later reads SHALL recheck. Confirmed metadata SHALL be refreshed after the namespace epoch advances. An ordinary collection replaced by a time-series collection SHALL cease being cache-eligible after the manager processes the ordinary collection's drop event. A namespace first observed absent and later created as time-series SHALL remain uncached without requiring a time-series change event. Ordinary collection caching, including negative document lookups in an existing ordinary collection, SHALL remain subject to the existing read eligibility rules.

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

#### Scenario: Time-series reads always reach MongoDB

- **WHEN** a caller repeats any supported read method on a time-series collection while the database stream is healthy
- **THEN** each call executes against MongoDB without a cache hit or admission, preserving options, return shape, and database errors
- **AND** successful calls increment bypass statistics rather than hit statistics

#### Scenario: An independent writer changes time-series data

- **WHEN** an independent client inserts a measurement after an earlier facade read and the insert is visible to an equivalent direct read
- **THEN** a subsequent facade read observes the database result without waiting for a time-series invalidation event

#### Scenario: An ordinary collection is replaced by time-series

- **WHEN** a cached ordinary collection is dropped, the manager processes its drop event, and the name is recreated as time-series
- **THEN** subsequent reads recheck collection type and bypass cache lookup and admission

#### Scenario: An absent name later becomes time-series

- **WHEN** a facade reads an absent namespace, and that name is subsequently created as a time-series collection
- **THEN** the absent read's result is not cached and later reads recheck the type and bypass, without relying on a time-series creation event

#### Scenario: An absent name later becomes an ordinary collection

- **WHEN** a facade reads an absent namespace and that name is later created as an ordinary collection
- **THEN** subsequent reads recheck the type and can cache eligible results, including missing-document results in the existing collection
