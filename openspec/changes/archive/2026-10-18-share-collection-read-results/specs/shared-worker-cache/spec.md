## MODIFIED Requirements

### Requirement: Public identity reads

Sync and asyncio shared managers SHALL attach user-owned PyMongo clients and cache deterministic `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count` and `distinct` reads across workers. Eligibility SHALL cover process-local query/options behavior subject to documented shared codec/collation restrictions. Managers SHALL preserve native bypass behavior and document types and SHALL NOT close user clients.

#### Scenario: Shared warm read

- **WHEN** a second worker requests an admitted identity
- **THEN** it reads the shared value without an owner round trip

#### Scenario: Unsupported read

- **WHEN** a worker uses a session or an unsafe query including `$$USER_ROLES`
- **THEN** the request executes directly through its PyMongo collection

#### Scenario: Explicit locale collation

- **WHEN** a read supplies a non-simple collation
- **THEN** it executes through PyMongo without entering shared caching

#### Scenario: Shared collection results

- **WHEN** one worker completes an eligible read and another worker first makes an equivalent request
- **THEN** the second worker receives the shared result without issuing the MongoDB read command

#### Scenario: Broader membership changes

- **WHEN** a collection write changes a filtered result, ordering or count
- **THEN** change-stream invalidation prevents reuse of the previous shared result

## ADDED Requirements

### Requirement: Shared cursor lifecycle

Shared `find` SHALL remain lazy and asyncio `aggregate` SHALL remain awaitable. Misses SHALL retain native batching and admit only fully consumed bounded snapshots. Partial consumption, close, failure or cancellation SHALL prevent admission. Hits SHALL remain isolated through invalidation, eviction and manager closure. Supported cursor modifiers, clone and rewind SHALL retain process-local behavior.

#### Scenario: Interrupted miss

- **WHEN** a cursor closes or fails after returning only part of its result
- **THEN** another worker cannot obtain that partial result as a shared hit

#### Scenario: Oversized read

- **WHEN** complete results exceed the shared entry bound
- **THEN** the caller receives every document without shared admission

#### Scenario: Owned hit snapshot

- **WHEN** a hit cursor exists while its shared entry is invalidated or its manager closes
- **THEN** consumption returns its own unmodified snapshot
