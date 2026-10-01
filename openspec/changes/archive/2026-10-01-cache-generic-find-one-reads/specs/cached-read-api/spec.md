# Spec Delta

## ADDED Requirements

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

## MODIFIED Requirements

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
