# Spec Delta

## Purpose

Selective invalidation lets process-local cached reads survive writes proved irrelevant to their results, while keeping conservative invalidation available for every uncertain case.

## ADDED Requirements

### Requirement: Collection policies are immutable constructor configuration

Both process-local `CacheManager` constructors SHALL accept an optional `invalidation` mapping from `(database, collection)` names to immutable `SelectiveInvalidation` values. The public type SHALL expose `insert_partition_field=None` and `update_dependencies_for_counts=False`. Configuration SHALL be snapshotted and validated before stream activation, and SHALL apply identically through indexed access and `get_cached_collection()`.

#### Scenario: Policies operate independently and together

- **WHEN** a manager configures either option alone or both options for one collection
- **THEN** only the enabled retention proofs apply to that collection, including when another collection activated its database stream first
- **AND** another manager using the same client retains its own policy

#### Scenario: Caller mutates the original mapping

- **WHEN** the caller changes the supplied mapping after manager construction
- **THEN** the manager continues using its original configuration without changing an active stream

#### Scenario: Invalid configuration is supplied

- **WHEN** an entry has malformed namespace names, a non-policy value, a non-Boolean update flag, or a partition field that is not a nonempty top-level name without dots, a leading `$`, or NUL
- **THEN** construction raises `CacheConfigurationError` before opening streams

#### Scenario: Configuration is absent or disabled

- **WHEN** `invalidation` is omitted, empty, or contains only policies with both options disabled
- **THEN** the existing invalidation behavior and routing-only projection apply without selective query analysis or retained selective state

### Requirement: Insert partition proofs preserve unrelated results

An enabled insert policy SHALL retain otherwise cacheable `find()` and `count_documents()` results when their filter proves equality to one supported scalar on the configured field and a processed insert proves a different partition. Additional conjunctive predicates SHALL NOT prevent this proof. Other read methods SHALL retain their existing invalidation rules.

#### Scenario: An insert belongs to another author

- **WHEN** results for `{"author_id": 42, "published": True}` are cached and an insert with scalar `author_id=99` is processed
- **THEN** repeated matching finds and counts remain hits, including sorted, skipped, limited, and empty find results

#### Scenario: An insert can affect the result

- **WHEN** an insert has a matching partition or its partition is missing, null, an array, an object, oversized, or otherwise unproved
- **THEN** affected results and in-flight admissions are invalidated conservatively

#### Scenario: The query does not establish one partition

- **WHEN** an otherwise cacheable filter has no partition equality, conflicting equalities, a disjunction, a null or array equality, or another unsupported partition shape
- **THEN** it retains ordinary caching with collection-wide insert invalidation, independently of any supported update-dependency proof

### Requirement: Partition comparison preserves BSON matching semantics

Partition proofs SHALL support BSON integers, strings, and `ObjectId` values. Equal numeric values across integer, double, and decimal BSON types SHALL never be treated as unrelated. Booleans SHALL remain distinct from numbers. Non-simple or unknown effective collation and unsupported scalar types SHALL use conservative fallback rather than an unsafe comparison.

#### Scenario: An integer query receives a numerically equal insert

- **WHEN** a cached partition equals integer `42` and an inserted value is double `42.0` or decimal `42`
- **THEN** that insert invalidates the result, through equal-partition routing or conservative fallback

#### Scenario: Distinct supported scalar partitions

- **WHEN** distinct supported strings or `ObjectId` values are queried and inserted under simple effective collation
- **THEN** the unrelated insert preserves the cached result

#### Scenario: A collection supplies its default collation

- **WHEN** a read omits an explicit collation and the collection default is non-simple
- **THEN** partition retention is disabled for that read, while an eligible explicit simple override can establish a proof

### Requirement: Count dependencies are inferred conservatively

An enabled count-dependency policy SHALL automatically derive fields from supported `count_documents()` predicates and retain a result through an update only if no changed field overlaps those dependencies. Unsupported predicates or incomplete event information SHALL retain collection-wide update invalidation. Users SHALL NOT supply dependency lists.

#### Scenario: An unrelated update preserves a count

- **WHEN** a count for `{"author_id": 42}` is cached and a processed update changes only `views`
- **THEN** it remains a hit, while changing or removing `author_id` invalidates it

#### Scenario: Parent paths and array changes overlap

- **WHEN** a count depends on `profile.country` or `tags`, and an update replaces `profile`, changes a relevant descendant, or truncates the relevant array
- **THEN** the count is invalidated
- **AND** ambiguous dotted or numeric event paths cannot establish independence

#### Scenario: Null and missing predicates have dependencies

- **WHEN** a supported count predicate tests null, missing, or existence on a field
- **THEN** that field remains a dependency even if its cached count is zero

#### Scenario: Count options and unsupported filters

- **WHEN** an otherwise cacheable count has skip, limit, hint, collation, or a predicate outside supported dependency extraction
- **THEN** its existing key distinctions, native results, validation, and errors remain intact
- **AND** unsupported dependency extraction falls back to ordinary update invalidation without disabling a separately supported insert proof or introducing a cache bypass

### Requirement: Retention proofs compose by operation

A result SHALL survive a processed write only when an enabled proof covers that operation. Combined policies SHALL NOT use an insert proof to excuse an update, or a dependency proof to excuse an insert. Replacements and deletions SHALL invalidate all selectively guarded results in the collection. Updates SHALL invalidate partitioned finds regardless of their changed fields.

#### Scenario: Both policies protect one count

- **WHEN** a partitioned author count has both policies enabled
- **THEN** an unrelated scalar insert and an unrelated-field update each preserve it
- **AND** a matching or unknown insert, relevant or unknown update, replacement, or deletion invalidates it

#### Scenario: Only one policy is enabled

- **WHEN** a partitioned count receives an update without dependency retention, or a dependency count receives an insert without partition retention
- **THEN** ordinary collection-wide invalidation applies to that result

### Requirement: Selective guards preserve continuity and bounded ownership

Selective lookup and admission SHALL preserve namespace epochs, index generations, database availability, identity invalidation, and eviction guarantees. Selective metadata SHALL have finite manager-wide capacity independent of historical partition and collection cardinality, including detached owners retained by active captures. Unreferenced metadata SHALL be reclaimed. Capacity exhaustion SHALL fall back safely without reviving an obsolete guard.

#### Scenario: Partition churn exceeds metadata capacity

- **WHEN** partitions across many collections are read and written, entries are replaced or evicted, and captures finish or survive collection recreation
- **THEN** retained selective metadata stays within its documented internal bound and released slots become reusable
- **AND** a delayed capture cannot validate against a different owner reusing its slot

#### Scenario: Concurrent captures compete for the final capacity slot

- **WHEN** reads in different namespaces concurrently acquire distinct new proof groups at the manager-wide capacity boundary, with the record-count limit disabled or enabled
- **THEN** combined group ownership stays within capacity and acquisitions without a slot fall back to ordinary guards

#### Scenario: A partially consumed cursor becomes unreachable

- **WHEN** a sync or async cursor with an active selective capture becomes unreachable without explicit close and is collected
- **THEN** its incomplete result is not admitted and its ownership cannot permanently consume selective capacity
- **AND** the next group acquisition can reclaim the abandoned owner without deadlock, explicit close, or a running event loop

#### Scenario: Stream continuity or namespace identity changes

- **WHEN** stream interruption/recovery, collection drop/recreation, rename, database drop, invalidation, or manager closure crosses a selective capture
- **THEN** no obsolete result is admitted or reused after the transition

#### Scenario: An index changes

- **WHEN** an index event advances index metadata generations
- **THEN** selectively guarded entries and admissions honor that change without weakening existing identity or metadata handling

### Requirement: Opt-in guidance explains cost and consistency

Public documentation SHALL describe configuration, supported queries, fallback, capacity behavior, independent options, and practical workload trade-offs. It SHALL link the existing eventual-consistency contract and explain that selective retention adds no read-after-write barrier. `SharedCacheManager` SHALL NOT expose this policy.

#### Scenario: A user chooses a policy

- **WHEN** the user reads the API and usage guides
- **THEN** sync and asyncio examples show an author feed and count, identify the additional stream cost, and explain when saved database reads can justify it
- **AND** ordinary reads and raw access remain available under their existing contracts
