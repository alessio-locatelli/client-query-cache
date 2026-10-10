## ADDED Requirements

### Requirement: Search-backed aggregations execute natively

Aggregation pipelines that query MongoDB Search or Vector Search indexes, or list search indexes, SHALL execute natively with the caller's effective read concern and without cache lookup or admission.

#### Scenario: A search pipeline runs with unspecified read concern

- **WHEN** a caller runs an aggregation pipeline containing a `$search`, `$searchMeta`, `$vectorSearch`, or `$listSearchIndexes` stage, at top level or inside another stage's sub-pipeline, on a collection without an explicit read concern
- **THEN** the facade executes the pipeline without imposing majority read concern and returns the native result or error

#### Scenario: A search pipeline is repeated

- **WHEN** a caller repeats the same search-backed aggregation pipeline
- **THEN** every execution reaches MongoDB and none is served from or admitted to the cache, so asynchronous search indexing and search-index changes remain visible to later calls

## MODIFIED Requirements

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

#### Scenario: A read depends on index configuration

- **WHEN** a caller runs a `find_one`, `find`, `count_documents`, or `distinct` read whose filter contains `$text`, `$near`, or `$nearSphere`, or an aggregation pipeline containing `$text` or a `$geoNear` stage
- **THEN** the facade executes the read and returns its result without admitting it to the cache, so a later call after a text or geospatial index is created, dropped, hidden, or redefined returns the native result or error for the current indexes

#### Scenario: A read depends on the caller's roles

- **WHEN** a caller runs a `find_one`, `find`, `count_documents`, or `distinct` read whose filter references `$$USER_ROLES`, a `find_one` or `find` read whose projection references it, or an aggregation pipeline that references it
- **THEN** the facade executes the read and returns its result without admitting it to the cache, so a later call after the authenticated user's roles change is not frozen to the roles at the first execution

#### Scenario: A projection computes a variable value

- **WHEN** a caller runs a `find_one` or `find` read whose projection contains a `$rand` or `$function` expression, or references `$$NOW` or `$$CLUSTER_TIME`
- **THEN** the facade executes the read and returns its result without admitting it to the cache, so a later call is not frozen to the first computed value
