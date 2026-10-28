# Shared Worker Cache Specification

## Purpose

Provide an installable cache shared by trusted application workers on one host, with explicit lifecycle and bounded failure behavior.

## Requirements

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

### Requirement: Validity and recovery

Hits and admissions SHALL respect writes, generations, availability, owner incarnation and progress expiry. A silent stall SHALL disable hits within three seconds. Owner failure SHALL fall back to MongoDB, and restart SHALL discard old attachment metadata before serving fresh shared values. Consistency SHALL remain eventual as with the process-local cache.

#### Scenario: Miss crosses invalidation

- **WHEN** invalidation occurs between miss capture and admission
- **THEN** the captured value cannot become a shared hit

#### Scenario: Owner restart

- **WHEN** an owner is restarted at the same endpoint
- **THEN** workers reconnect without reviving its previous shared state

#### Scenario: Replacement starts during an outage

- **WHEN** a new worker attaches while the owner is temporarily unreachable
- **THEN** its manager permits direct reads and retries shared attachment after recovery
- **AND** explicit credential, configuration and persistent-access errors remain visible

### Requirement: Explicit process lifecycle

The public server SHALL spawn its owner, report startup failures, provide a transferable connection and support bounded idempotent shutdown and explicit restart. Parent loss SHALL stop the owner. Managers SHALL release attachments on close, reject reads after close and reject inherited use after fork. Async cleanup SHALL complete before propagating cancellation.

#### Scenario: Worker replacement

- **WHEN** a spawned worker exits and another attaches
- **THEN** the replacement uses its own client and attachment without taking ownership of the server

#### Scenario: Shutdown

- **WHEN** the parent closes the server
- **THEN** the owner is reaped and its private endpoint is removed

### Requirement: Trusted attachment boundary

The server SHALL use a private owner-only runtime directory, a random capability, same-user peer checks and sealed read-only value mappings. Attachment credentials and MongoDB URIs SHALL be absent from representations and diagnostics. All attached workers SHALL belong to one application security principal; the API SHALL document that the connection grants access to all configured databases.

#### Scenario: Unauthorized attachment

- **WHEN** a peer supplies the wrong capability
- **THEN** it receives no mapping or cached values and other workers remain usable

### Requirement: Bounded resources

Configuration SHALL validate built-in positive integer limits and native layout bounds before allocating resources. Index slots SHALL be a power of two and connection capacity SHALL be at least two. Cache entries, arena, index, connection queues and captures SHALL have finite limits. Oversized values or full queues SHALL preserve successful MongoDB reads without unbounded retention. Documentation SHALL distinguish the cache accounting budget from total process memory.

#### Scenario: Full admission queue

- **WHEN** a worker cannot publish an admission locally
- **THEN** it uses bounded transport fallback or skips admission

#### Scenario: Large identity encoding

- **WHEN** a key's encoded size exceeds the worker encoding-cache admission threshold
- **THEN** the key remains usable without retaining its canonical or encoded form in that cache

### Requirement: Stable collection deployment

Shared caches SHALL support collection-name churn without unbounded namespace metadata. Collection drops SHALL release owner namespace slots. When all configured slots are occupied, reads for additional namespaces SHALL preserve MongoDB behavior and bypass shared caching. Guidance SHALL explain sizing, reclamation and capacity bypass.

#### Scenario: Deployment sizing

- **WHEN** an operator configures the server for an application
- **THEN** `namespaces` limits simultaneous tracked database/collection pairs, dropped collections release slots, and names beyond capacity bypass shared caching

#### Scenario: Shared namespace capacity is exhausted

- **WHEN** a read targets a new namespace while every configured shared slot is assigned
- **THEN** the read completes through MongoDB without retaining metadata for that namespace

### Requirement: Worker namespace metadata is bounded

Each shared worker SHALL retain no more than the configured `namespaces` count in its local namespace metadata and slot maps. Each map SHALL evict its oldest stored entry when its capacity is reached.

#### Scenario: A worker sees more names than its configured capacity

- **WHEN** a worker accesses more distinct namespace names than `namespaces`
- **THEN** both local maps remain within the configured capacity and evicted names can refresh metadata later

### Requirement: Reused shared slots reject stale readers

Reusing a shared namespace slot SHALL advance its epoch so captures and local readers holding the prior assignment cannot observe entries published for the new namespace. Owner restart SHALL continue to fence readers by owner incarnation.

#### Scenario: A stale worker holds a recycled slot

- **WHEN** a namespace slot is reassigned while a worker retains the old namespace epoch
- **THEN** the reader rejects the stale lookup and cannot return the new namespace's value

#### Scenario: The owner restarts after slot reuse

- **WHEN** the shared owner restarts while workers retain previous namespace slots
- **THEN** those slots are unusable under the new owner incarnation until refreshed

### Requirement: Release distribution and guidance

The package SHALL include public shared APIs and the native index in one PyPI distribution, with Linux x86-64 and ARM64 glibc 2.28+ CPython 3.14+ wheels and a buildable locked-source sdist. Installed artifacts SHALL start the owner outside the checkout. Public guides and Context7 SHALL specify supported deployment, scope, consistency and cleanup, and provide reproducible performance evidence for public reads.

#### Scenario: Compiler-free application install

- **WHEN** a supported application installs the release wheel
- **THEN** it can attach sync and async workers without a Rust toolchain or benchmark package

#### Scenario: ARM64 application uses both cache modes

- **WHEN** a Linux ARM64/glibc application meets the documented Python, MongoDB and shared-host prerequisites
- **THEN** process-local and shared sync/async caching provide the same public contracts as Linux x86-64

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

### Requirement: Shared find preparation reuses portable query encodings

Shared find key preparation SHALL serialize a query family at most once when both exact local lookup and owner selection need encodings. The resulting keys SHALL preserve existing wire bytes, scalar distinctions, errors and owner selection behavior. Reuse SHALL remain bounded; oversized encodings SHALL remain usable without retention.

#### Scenario: A local miss selects through the owner

- **WHEN** an eligible shared find misses its exact local lookup
- **THEN** owner selection reuses the prepared family encoding without traversing the query again
- **AND** exact, covering and unlimited reuse retain their existing results

#### Scenario: A limit has a specialized integer representation

- **WHEN** a find uses a negative or BSON Int64 limit
- **THEN** its exact key and owner request retain the existing representation and selection semantics

#### Scenario: Portable keys exceed the retention bound

- **WHEN** a valid query produces keys larger than the key-cache retention bound
- **THEN** the current read can use those keys without retaining them or repeating query serialization

#### Scenario: A worker has no local index

- **WHEN** a worker cannot perform local lookup
- **THEN** it prepares only the existing owner-selection key and retains current admission and fallback behavior
