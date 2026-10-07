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

- **WHEN** a caller needs native execution of `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, or `distinct`, even when a cached entry exists
- **THEN** the caller reaches the wrapped PyMongo object through `.raw` and calls the method there, bypassing the facade's override entirely

### Requirement: Incomplete results are not admitted

The facades SHALL admit only complete, bounded results of supported reads after successful consumption, guarded by the namespace and stream-availability generations captured before native execution.

#### Scenario: A caller abandons a cursor

- **WHEN** a caller partially consumes a cacheable-looking cursor
- **THEN** the facade does not admit its incomplete result to the cache

#### Scenario: The server exhausts before the caller consumes its batch

- **WHEN** the server cursor is exhausted but the caller leaves delivered batch documents unread
- **THEN** the facade does not admit the unread result

#### Scenario: Bounded to_list calls consume only a prefix

- **WHEN** a caller requests a prefix with `to_list(length=...)` and leaves documents unread
- **THEN** no entry is admitted until later calls consume the complete result

#### Scenario: An empty result is fully consumed

- **WHEN** a supported read successfully establishes that it has no documents
- **THEN** its empty result can be admitted under the same generation guards

#### Scenario: Execution fails after delivering documents

- **WHEN** a later batch raises a native error or cancellation interrupts execution
- **THEN** the incomplete result is not admitted and the error or cancellation propagates

#### Scenario: An invalidation or stream transition races consumption

- **WHEN** a write, namespace change, stream availability transition, or manager closure occurs between capture and full consumption
- **THEN** the result is not admitted under the obsolete capture

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

Session-bound reads SHALL bypass cache lookup and admission whether the session is supplied explicitly or inherited from a bound context. Explicit non-`None` sessions SHALL retain native precedence over bound contexts. Delegation SHALL preserve native session validation and errors. If effective-session resolution is unavailable or fails, reads SHALL bypass caching and execute natively.

#### Scenario: A session-bound read is requested

- **WHEN** a caller supplies a PyMongo session to a supported read
- **THEN** the facade delegates directly to PyMongo without a cache hit or admission

#### Scenario: A bound transaction repeats a warm query

- **WHEN** a caller binds a session, modifies a document in its transaction, and repeats a warm cached read with an omitted session or explicit `None`
- **THEN** the read executes in that transaction and observes its writes without a cache hit or admission

#### Scenario: A cold bound read returns session-scoped data

- **WHEN** a caller performs a cold supported read in a bound context
- **THEN** the facade executes the native read without admitting its result or negative result to the shared cache

#### Scenario: Native session restrictions apply after warming

- **WHEN** a warm supported read is repeated with an ended session, a different client's bound context, or a method that disallows sessions
- **THEN** the facade preserves the native validation error and its precedence over competing malformed arguments rather than returning the warm entry

#### Scenario: An explicit session overrides a bound context

- **WHEN** a caller supplies a non-`None` session while a different session is bound
- **THEN** the facade delegates using the supplied session and preserves PyMongo's validation behavior without a hit or admission

#### Scenario: A bound context exits

- **WHEN** a caller leaves a bound context and performs an otherwise eligible read in an unbound context
- **THEN** the read can use ordinary caching without inheriting the exited session

#### Scenario: Async execution contexts have distinct sessions

- **WHEN** one async execution context binds a session while another remains unbound
- **THEN** each read uses its own context, with only the bound read bypassing caching

#### Scenario: Effective-session capability is unavailable

- **GIVEN** the native client has no callable effective-session resolver
- **WHEN** a supported read is requested
- **THEN** the facade bypasses cache lookup and admission and executes the native read

#### Scenario: Effective-session inspection fails

- **WHEN** effective-session inspection raises an ordinary exception
- **THEN** the facade bypasses lookup and admission and lets the native read determine its result or error

### Requirement: Unestablished streams bypass caching

Reads SHALL bypass caching when the database change stream cannot be established.

#### Scenario: A database's change stream cannot be established

- **WHEN** a caller performs a supported read against a database whose change stream fails to start
- **THEN** the facade executes the read and returns its result without a cache hit or admission, instead of raising

### Requirement: Unique-key eligibility follows index metadata

The facades SHALL use only unconditional unique indexes with locally confirmed matching effective collation for unique-key aliases. A single-document read's effective collation SHALL include a supported explicit override or the collection's default when no override is supplied.

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

### Requirement: Unconfirmed explicit collation uses namespace caching

An explicit collation whose omitted locale-specific defaults prevent locally confirming equivalence with a unique index SHALL use generic namespace caching.

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

Synchronous and asyncio cached single-document reads SHALL cache deterministic mapping filters that do not qualify for an exact identity or unique-key optimization, including compound predicates, regex-ID queries, and match-all reads. Their entries SHALL be guarded against writes anywhere in the queried collection and against namespace or stream-continuity changes. Negative results SHALL be cacheable under the same guard.

#### Scenario: A caller repeats a compound predicate

- **WHEN** a caller repeats an eligible single-document query with an `_id` equality and an additional predicate
- **THEN** the repeated query can hit a namespace-guarded entry without ignoring the additional predicate

#### Scenario: A caller repeats a regex-ID query

- **WHEN** a caller repeats an eligible single-document query whose `_id` predicate is a regular expression
- **THEN** the repeated query can hit a namespace-guarded entry rather than being treated as an exact-identity or unique-key read

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

### Requirement: Ineligible single-document reads execute directly

Unsafe filters or projections, session-bound reads, unsupported options, uncanonicalizable inputs, incompatible read profiles, and ineligible collections or streams SHALL retain direct execution of single-document reads with the original arguments and errors.

#### Scenario: Unsafe query input follows a cached safe query

- **WHEN** a caller supplies a nondeterministic or otherwise unsafe filter or projection
- **THEN** the read executes through the original database operation without a hit or admission, even if another safe query was previously cached

### Requirement: Single-document sort and collation are explicit

Both execution models SHALL expose explicit keyword-only sorting and collation options on cached single-document reads. Generic cache keys SHALL distinguish every output-affecting predicate, projection, ordered sort specification, effective collation, and decoding profile. Valid equivalent default forms SHALL have consistent matching semantics.

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

### Requirement: Cached single-document results match the database operation

Cached single-document results SHALL preserve the database's single-document return shape and SHALL NOT promise ordering beyond that of the corresponding database operation.

#### Scenario: An unsorted query matches several documents

- **WHEN** a cached single-document read without a sort matches several documents
- **THEN** the result is a single document, as the database operation returns, and the cache guarantees no more about which matching document is selected than the database does

### Requirement: Invalid single-document options do not hit cached entries

A malformed or unsupported single-document read option SHALL NOT hit a previously valid entry or mask the database driver's error.

#### Scenario: A malformed option follows a warm entry

- **WHEN** a caller repeats a warm query with a malformed sort or collation argument
- **THEN** the malformed request does not return the warm result and preserves the appropriate driver error

#### Scenario: An unsupported extra option is supplied

- **WHEN** a caller supplies an option outside the explicitly supported cache contract
- **THEN** the original single-document operation executes directly with that option rather than silently discarding it

### Requirement: Count reads preserve explicit options

Synchronous and asyncio cached `count_documents` reads SHALL preserve explicitly supplied options in native execution. Cache keys SHALL distinguish options with different native behavior, including invalid bounds and `hint=None`, while omitted skip and integer `skip=0` SHALL share a cache shape. Omitted bounds SHALL count all matching documents. Native PyMongo/MongoDB errors SHALL propagate on cold and bypassed reads without reusing incompatible warm entries. General live-error policy is unchanged.

#### Scenario: Bounds are omitted

- **WHEN** a caller repeats an eligible count without `skip` or `limit`
- **THEN** all matching documents are counted and the result can be cached

#### Scenario: An explicit invalid option is supplied

- **WHEN** a caller supplies `limit=0`, `limit=None`, `skip=None`, or `hint=None` on a cold count or after warming an omitted-option count
- **THEN** the native error is preserved instead of returning the omitted-option count

#### Scenario: A count bypasses caching

- **WHEN** a caller supplies an explicit invalid option on a count that bypasses caching
- **THEN** native execution receives that value and preserves its error

#### Scenario: Zero skip is equivalent to omission

- **WHEN** a caller warms an eligible count with omitted skip and repeats it with `skip=0`, or performs these calls in reverse order
- **THEN** the repeated read reuses the same cached entry
- **AND** an explicit zero skip reaches native execution unchanged when that request performs the cold read

### Requirement: Multi-document reads preserve native cursor call shapes

Synchronous `find()` and `aggregate()` SHALL return cursors directly, asynchronous `find()` SHALL return its cursor without awaiting, and asynchronous `aggregate()` SHALL return its cursor when awaited. Calls SHALL accept the corresponding PyMongo method's positional and keyword arguments.

#### Scenario: Shared synchronous read code

- **WHEN** the same function calls `collection.find(...).sort(...).skip(...).limit(...)` or iterates `collection.aggregate(...)` using a native collection and a cached view
- **THEN** both calls work without changing the consuming function

#### Scenario: Shared asynchronous read code

- **WHEN** the same async function uses `async for document in collection.find(...)` and `cursor = await collection.aggregate(...)` with either collection
- **THEN** both forms work without adding an await to `find()`

#### Scenario: Positional options are passed

- **WHEN** a caller uses positional options accepted by the installed PyMongo method
- **THEN** the cached method binds them with native argument semantics, including errors for duplicate arguments

### Requirement: Find cursor construction is lazy

`find()` SHALL perform native local argument validation at construction and defer database queries, metadata probes, stream activation, and cache lookup until consumption or another native operation requiring execution.

#### Scenario: A cursor is never consumed

- **WHEN** a caller constructs a valid `find()` cursor and closes it without executing it
- **THEN** no database read, metadata probe, stream activation, cache lookup, or admission is performed

#### Scenario: Invalid constructor options follow warming

- **WHEN** a caller constructs a cursor with locally invalid PyMongo arguments after warming a related valid query
- **THEN** the constructor raises the native validation error rather than returning cached data

### Requirement: Cursor types preserve native public interfaces

Results of `find()` and `aggregate()` SHALL be instances of the corresponding PyMongo `Cursor`, `AsyncCursor`, `CommandCursor`, or `AsyncCommandCursor` type, including permitted subclasses. Public methods SHALL retain their native return shapes, await conventions, and local validation errors.

#### Scenario: A caller checks the cursor type

- **WHEN** a caller receives a cold, warm, or bypassed cursor
- **THEN** `isinstance` against the corresponding native cursor class succeeds

#### Scenario: Native cursor operations are used

- **WHEN** a caller uses supported iteration, `next`, `to_list`, `close`, context management, or command-cursor `try_next`
- **THEN** the result and state transitions follow that native cursor interface

#### Scenario: Async indexing is attempted

- **WHEN** a caller indexes an async find cursor where PyMongo rejects indexing
- **THEN** the cached cursor preserves that rejection

### Requirement: Chaining determines the executed query

Find cursor cache identity SHALL reflect its final output-affecting options before execution. Options or operations outside the supported cache contract SHALL execute natively without cache lookup or admission.

#### Scenario: A chained query differs from its constructor

- **WHEN** a caller constructs `find({})` and applies sort, skip, limit, or collation before consuming it
- **THEN** results and cache identity reflect the final query rather than the constructor's original shape

#### Scenario: A native-only option follows a warm query

- **WHEN** a caller uses a hint, comment, timeout, arbitrary flag, or another option outside the supported cache contract
- **THEN** that option reaches PyMongo without reusing a warm entry that would skip its server behavior

#### Scenario: Chaining follows consumption

- **WHEN** a caller changes an option that PyMongo forbids changing after execution starts
- **THEN** the cached cursor raises the native error, including on a hit

#### Scenario: A caller asks for explain or cursor distinct

- **WHEN** a caller invokes `explain()` or the find cursor's `distinct()` method
- **THEN** that operation executes natively with its original options instead of answering from cached find documents

### Requirement: Cursor re-execution has independent state

Find cursor cloning, copying, rewinding, and synchronous indexing or slicing SHALL follow native query semantics with independent consumption and admission state for each resulting execution.

#### Scenario: A consumed cursor is cloned

- **WHEN** a caller clones a partially or fully consumed find cursor
- **THEN** the clone begins unevaluated with the same query options and does not reuse the original cursor's position or incomplete candidate

#### Scenario: A cursor is rewound

- **WHEN** a caller rewinds a find cursor and consumes it again
- **THEN** it starts a new execution that rechecks eligibility and current cache generations without replaying an obsolete private snapshot

#### Scenario: Synchronous indexing follows a limit

- **WHEN** a caller uses an integer index or slice on an unevaluated synchronous find cursor
- **THEN** native skip/limit semantics apply rather than indexing a list cached for a different query

### Requirement: Cursor misses stream without eager draining

On a miss or bypass, multi-document reads SHALL fetch through native batching as requested by the caller without draining remaining results or adding per-document remote calls for caching. Aggregation SHALL retain its native initial-command timing.

#### Scenario: Only the first document is requested

- **WHEN** a caller requests one document from a multi-batch miss and then stops
- **THEN** caching causes no getMore calls to drain remaining batches

#### Scenario: An aggregation cursor is requested

- **WHEN** a caller calls synchronous `aggregate()` or awaits asynchronous `aggregate()` on a miss or bypass
- **THEN** the initial aggregation command runs before the cursor is returned, and subsequent batches remain caller-driven

### Requirement: Cursor candidates have bounded storage

The encoded payload retained for a cursor's cache-admission candidate SHALL be bounded by the configured maximum entry size, excluding transient document encoding and finalization. Exceeding that size or being unencodable SHALL discard the candidate without truncating the returned stream. This payload bound SHALL NOT be presented as a process-memory limit.

#### Scenario: An oversized result is consumed

- **WHEN** the encoded candidate exceeds the entry-size limit before exhaustion
- **THEN** retained candidate storage is released, subsequent documents are delivered normally, and no result is admitted

#### Scenario: A returned value cannot be encoded

- **WHEN** candidate encoding cannot represent a successfully returned document
- **THEN** the cursor continues with native results without admitting that execution

### Requirement: Admission preserves documents before caller mutation

Cursor admission SHALL preserve each returned document's value before the caller can mutate it, and hits SHALL provide isolated mutable results for each cursor.

#### Scenario: An early document is changed before exhaustion

- **WHEN** a caller mutates the first delivered document and later consumes the rest of the cursor
- **THEN** a subsequent hit returns the original document value rather than the caller's mutation

#### Scenario: Two hit cursors are consumed independently

- **WHEN** a caller mutates a document from one hit cursor
- **THEN** another hit cursor and the stored entry retain their original values

### Requirement: A started hit retains one result snapshot

Once a cursor starts consuming a valid hit, its remaining documents SHALL come from that isolated result snapshot. Namespace invalidation, stream uncertainty, or manager closure SHALL prevent subsequent executions from reusing that entry without restarting or mixing the current cursor's result.

#### Scenario: A write invalidates a partially consumed hit

- **WHEN** invalidation occurs after a hit cursor has delivered its first document
- **THEN** the cursor finishes its original snapshot, and a new cursor cannot use the invalidated entry

#### Scenario: Stream health changes during a hit

- **WHEN** stream continuity becomes uncertain during a started hit
- **THEN** that cursor retains its snapshot, while new executions bypass cache use until health is restored

#### Scenario: A manager closes with a hit in progress

- **WHEN** the manager closes after a hit cursor has started
- **THEN** the cursor can finish its isolated snapshot without reopening streams or accessing the closed cache

### Requirement: Hit cursor metadata describes local results

Hit cursors SHALL report no live server cursor: `cursor_id` is zero, `address` and `session` are `None`, and `alive` reflects remaining local documents. Find cursors SHALL expose the wrapped native collection and report `retrieved` as documents loaded into their local result buffer.

#### Scenario: A nonempty hit is opened

- **WHEN** a caller starts a hit containing several documents
- **THEN** metadata identifies a local result, and find `retrieved` counts the loaded snapshot rather than only documents consumed

#### Scenario: A hit is closed or exhausted

- **WHEN** the caller closes the hit cursor or consumes its remaining documents
- **THEN** `alive` becomes false and no killCursors command or implicit server session is created for that hit

### Requirement: Cursor cleanup does not own the client

Closing a cursor or exiting its context SHALL release its native resources, private result buffers, and incomplete admission candidate without closing the caller-owned client. Async cancellation SHALL discard incomplete candidates and perform awaited native cleanup.

#### Scenario: A context exits early

- **WHEN** a caller exits a cursor context before full consumption
- **THEN** its incomplete candidate is released, native cursor resources are closed, and the client remains usable

#### Scenario: An async read is cancelled

- **WHEN** cancellation interrupts a cursor read
- **THEN** cleanup releases the candidate and native resources and propagates cancellation without admitting partial data

### Requirement: Batching options known before execution bypass caching

Find batch-size options selected before execution and aggregation `batchSize` options supplied at invocation SHALL bypass cache lookup and admission while retaining native validation, initial-command timing, and batching.

#### Scenario: A find cursor is configured before consumption

- **WHEN** a caller supplies find `batch_size` or calls `find(...).batch_size(...)` before execution
- **THEN** the cursor executes natively without a hit or admission, including when a related query is warm

#### Scenario: Aggregate receives an explicit batchSize

- **WHEN** a caller supplies `batchSize` to `aggregate()` on a warm query
- **THEN** the initial command executes before the cursor is returned, with native batching and no cache lookup or admission

### Requirement: Later command-cursor batching retains the selected execution

`CommandCursor.batch_size()` and its asynchronous counterpart SHALL retain native validation and return the same cursor without changing the already selected execution. On a native cursor it SHALL affect subsequent getMore operations; on a local hit it SHALL have no remote batching effect or trigger native execution.

#### Scenario: A local aggregation hit is configured

- **WHEN** a caller invokes `batch_size(...)` before or during consumption of a local aggregation hit
- **THEN** valid input returns the same cursor, invalid input raises the native error, and no aggregate or getMore command is issued

#### Scenario: A native aggregation cursor is configured

- **WHEN** a caller invokes `batch_size(...)` on a miss or bypass after the initial command has executed
- **THEN** subsequent getMore operations use the native batch setting without rerunning the initial command or changing that execution's admission eligibility

### Requirement: Cursor-only requests execute natively

`find()` SHALL delegate tailable, exhaust, and partial-result requests and `aggregate()` SHALL delegate `$changeStream` pipelines natively without cache lookup, admission, or eager materialization.

#### Scenario: A cursor-only find request is supplied

- **WHEN** a caller requests a tailable or exhaust cursor or enables partial results
- **THEN** the caller receives the corresponding native cursor or native error without eager draining or caching

#### Scenario: An aggregation pipeline requests a change stream

- **WHEN** a caller runs a `$changeStream` pipeline
- **THEN** PyMongo supplies the native command cursor or native error without cache lookup or admission

### Requirement: Positive find limits can reuse complete covering results

Both execution models SHALL satisfy a cache-eligible `find()` with a positive integer limit from a valid complete result whose declared limit is an equal or larger positive integer, or zero for unlimited. All other cache-relevant inputs SHALL match. The returned result SHALL be the source's prefix of at most the requested length. Boolean and negative limits SHALL NOT participate in compatible lookup.

#### Scenario: A larger limited result supplies a prefix

- **WHEN** `find(filter, sort=[("_id", 1)], limit=100)` is fully consumed and admitted, then the otherwise identical `limit=10` cursor is consumed
- **THEN** it returns the first ten source documents without issuing a MongoDB find or getMore command, in both synchronous and asyncio APIs

#### Scenario: An unlimited complete result supplies a prefix

- **WHEN** an omitted-limit or integer `limit=0` result is fully consumed and admitted, then the otherwise identical `limit=10` cursor is consumed
- **THEN** it returns at most ten documents from that result without another MongoDB read

#### Scenario: A covering result contains fewer documents than requested

- **WHEN** a complete cached `limit=100` result has three documents, or is empty, and an otherwise identical `limit=10` cursor is consumed
- **THEN** it returns those three documents or the empty result without another MongoDB read

#### Scenario: A smaller limit cannot supply a larger request

- **WHEN** only a complete `limit=10` result is cached and an otherwise identical `limit=100` cursor is consumed
- **THEN** the request executes a MongoDB find command even if the smaller result exhausted all matching documents

#### Scenario: Unlimited and negative requests retain exact lookup

- **WHEN** a request has an omitted, zero, negative, or boolean limit and no exact entry, but a different-limit result is cached
- **THEN** it does not use compatible-result lookup and retains native execution and existing exact-key behavior

#### Scenario: Negative sources are not covering entries

- **WHEN** a complete negative-limit result is cached and a positive-limit query is consumed without an exact entry
- **THEN** that single-batch source cannot supply a compatible hit

### Requirement: Find compatibility preserves all remaining query boundaries

Compatible-result lookup SHALL use the final pre-execution filter representation, projection, ordered sort, skip, collation, codec profile, namespace, and all other cache-relevant inputs. Unsupported options SHALL retain existing bypass behavior. This change SHALL NOT introduce filter equivalence, normalize other query properties, or reuse aggregation results.

#### Scenario: Another output-affecting input differs

- **WHEN** a candidate differs in filter, projection, sort, skip, collation, codec profile, collection, or database from the positive-limit request
- **THEN** it is not a compatible source, and absent another matching source the request issues a MongoDB find command

#### Scenario: An unsupported cursor option follows warming

- **WHEN** a caller requests explicit batching, a hint, comment, session, or another unsupported cursor option after warming a covering result
- **THEN** native execution and validation occur without a compatible hit or admission

#### Scenario: Chained options determine the prefix request

- **WHEN** a caller sets sort, skip, collation, or limit through native chaining before consuming a cursor
- **THEN** compatibility uses the final shape rather than the constructor shape

### Requirement: Compatible cursors preserve isolation and native lifecycle

A compatible hit SHALL use the existing native cursor subclass with its usual validation, laziness, consumption, cleanup, clone, rewind, and started-snapshot contracts. Its private buffer SHALL contain only the requested isolated prefix, and `retrieved` SHALL count that loaded prefix. Consuming the hit SHALL NOT admit a duplicate prefix entry.

#### Scenario: A caller mutates a narrower hit

- **WHEN** a caller changes a nested value returned by a compatible `limit=10` hit
- **THEN** the resident source and later narrow and source-limit hits retain their original values

#### Scenario: Prefix metadata describes a local cursor

- **WHEN** a compatible cursor loads ten documents from a hundred-document source
- **THEN** `retrieved` is ten, `cursor_id` is zero, no server address or session is created, and exhausting or closing the cursor needs no remote cleanup

#### Scenario: A started prefix is invalidated

- **WHEN** invalidation occurs after the compatible cursor starts consuming its prefix
- **THEN** that cursor retains its isolated snapshot and a subsequent execution cannot reuse the invalidated source

#### Scenario: A source cursor is only partially consumed

- **WHEN** the caller consumes ten documents from a cold `limit=100` or unlimited cursor and closes it
- **THEN** that incomplete execution supplies no compatible result to a later narrower cursor

### Requirement: Top-level scalar predicate order shares find identity

Both execution models SHALL share find identity across permutations of plain dictionaries with exact built-in string fields not starting with `$` and values of None or exact built-in bool, int, float, or str types, subject to existing key eligibility and type distinctions. Unsupported forms SHALL retain ordered identity and existing eligibility. Normalization SHALL leave native filters and other key dimensions unchanged and SHALL apply only to find cursors.

#### Scenario: Scalar predicates are reversed

- **WHEN** a fully consumed find query is repeated with supported scalar predicates in a different top-level order and otherwise identical inputs
- **THEN** the cached result is reused without a find/getMore command or duplicate resident payload

#### Scenario: A filter contains a document, array, or operator

- **WHEN** an otherwise cache-eligible filter falls outside the scalar rule
- **THEN** it remains cacheable by its ordered shape, and reordering it does not create an equivalence hit

#### Scenario: A normalized query misses

- **WHEN** a supported scalar filter is executed on a cache miss
- **THEN** native execution receives the caller's original filter order

#### Scenario: Another query input differs

- **WHEN** a read changes another output-affecting key input
- **THEN** normalization preserves that distinction and existing compatible-limit rules

### Requirement: The cached read view accessor names what it returns

The synchronous and asyncio managers SHALL provide `get_cached_collection(collection)` for requesting a cached read view of a caller-supplied PyMongo collection. The former `cached(collection)` name SHALL NOT remain available.

#### Scenario: A caller requests a cached view

- **WHEN** a caller passes a PyMongo collection from the manager's client to `get_cached_collection`
- **THEN** the manager returns the cached read view described by the existing view requirements

#### Scenario: A caller uses the former accessor name

- **WHEN** a caller invokes `cached(collection)` on a manager
- **THEN** the call raises `AttributeError`

### Requirement: Public manager members are documented or absent

Every public member of the synchronous and asyncio managers SHALL appear in the public guides or be absent from the public surface. Members that exist only to wire the manager to its cached views SHALL be private.

#### Scenario: A caller inspects the manager's public members

- **WHEN** a caller lists the public attributes of a manager
- **THEN** that list equals the documented set: `client`, `cache_core`, `get_cached_collection`, `snapshot`, `stream_health_snapshot`, `stream_cost_snapshot`, `active_stream_cost_databases`, and `close`
- **AND** an asyncio manager exposes the same names

#### Scenario: A caller looks for an eligibility probe

- **WHEN** a caller looks for `ensure_cache_eligible`, `cache_ineligibility_reason`, `default_collation_for`, or `unique_keys_for` on a manager
- **THEN** none is public, and cached reads still use them internally

### Requirement: Cached views expose only documented or PyMongo-mirroring members

`CachedDatabase` and `CachedCollection` SHALL expose as public members only the cached read methods and traversal that mirror PyMongo, plus `name`, `raw`, and their documented owner (`manager` or `database`).

#### Scenario: A caller inspects a cached view's public members

- **WHEN** a caller lists the public attributes of a cached database or collection
- **THEN** the list contains only those documented members, identically for synchronous and asyncio views
