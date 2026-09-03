## Purpose

Provide explicit PyMongo facades that accelerate eligible reads without
pretending that every PyMongo operation has cache-safe semantics.

## ADDED Requirements

### Requirement: Synchronous and asyncio facades
The library SHALL provide separate synchronous and native asyncio facades over
existing PyMongo database and collection objects on CPython 3.13 and later. The
facades SHALL use composition rather than subclassing PyMongo classes, and they
SHALL expose the same supported cache behavior in both execution models.

#### Scenario: Application wraps a synchronous collection
- **WHEN** an application supplies a synchronous PyMongo collection to the
  synchronous facade
- **THEN** eligible synchronous reads use the cache manager associated with the
  wrapped database

#### Scenario: Application wraps an asyncio collection
- **WHEN** an application supplies an asyncio PyMongo collection to the
  asyncio facade
- **THEN** eligible asynchronous reads await the same cache lifecycle and
  coherency rules as the synchronous facade

### Requirement: Eligible read operations
The facades SHALL cache successful, fully materialized results of `find_one`,
`find`, `aggregate`, `count_documents`, `estimated_document_count`, and
`distinct` when the request is cacheable and the cache manager is healthy.
`find` and `aggregate` results SHALL be cached only after complete consumption
within configured result-size limits; partially consumed, tailable, exhaust,
or otherwise streaming cursors SHALL be delegated without cache admission.

#### Scenario: Fully consumed bounded query result
- **WHEN** a cacheable `find` result is fully consumed and fits the configured
  entry limit
- **THEN** a later equivalent cacheable query can return the materialized
  result without another MongoDB read

#### Scenario: Partially consumed cursor
- **WHEN** a caller stops iterating a query cursor before it is exhausted
- **THEN** the library SHALL NOT cache that incomplete query result

### Requirement: Identity-aware lookup acceleration
The facades SHALL use document caching for `_id` equality lookups and for
exact-equality lookups on explicitly declared simple or compound unique keys.
Each cached document SHALL be associated with every identity key by which it
was admitted so a later document invalidation removes every alias.

#### Scenario: Declared unique-key hit
- **WHEN** a caller performs an exact-equality lookup matching a declared
  unique key and the matching document is cached
- **THEN** the facade returns a fresh value for that document without querying
  MongoDB

#### Scenario: Non-identity lookup
- **WHEN** a `find_one` filter does not match `_id` or a declared unique key
- **THEN** the facade can use the derived-result cache but SHALL NOT treat the
  filter as a document identity

### Requirement: Read consistency and bypass
The facades SHALL execute cacheable reads with primary read preference and
majority read concern. Session-bound reads and requests whose semantics cannot
use that consistency profile SHALL bypass all cache lookup and admission while
preserving their PyMongo behavior.

#### Scenario: Default cached read
- **WHEN** a caller issues an eligible read through a cached facade without a
  session
- **THEN** the read uses primary and majority semantics before its result is
  eligible for cache admission

#### Scenario: Session-bound read
- **WHEN** a caller supplies a PyMongo client session to a read
- **THEN** the facade delegates the read directly and does not read or write a
  shared cache entry

### Requirement: Value isolation and transparent fallback
The facades SHALL return caller-owned document and result values. The library
SHALL delegate unsupported operations directly to PyMongo and SHALL NOT label
them as cached or coherently invalidated.

#### Scenario: Caller mutates a returned document
- **WHEN** a caller modifies a document returned by a cache hit
- **THEN** a subsequent cache hit returns the original cached MongoDB value
  rather than the caller's mutation

#### Scenario: Unsupported operation
- **WHEN** a caller invokes an operation outside the documented eligible-read
  set
- **THEN** the operation executes through PyMongo without shared-cache use
