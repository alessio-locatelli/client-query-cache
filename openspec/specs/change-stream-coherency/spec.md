# change-stream-coherency Specification

## Purpose

This capability keeps a process-local cache safe to use only while a database-scoped MongoDB change stream can establish or restore known invalidation continuity.

## Requirements

### Requirement: Managers use one invalidation stream per database

A manager SHALL use one database-scoped change stream for each database it caches, opened with `show_expanded_events=True`.

#### Scenario: A client caches multiple databases

- **WHEN** a caller activates cached collections in more than one database through the same client
- **THEN** the manager maintains one independent database-scoped stream for each active cached database, and an event in one database cannot be routed as an invalidation for another database

### Requirement: Change-stream projection retains routing fields

The stream projection SHALL retain resume tokens and fields needed for event routing while omitting full documents and update descriptions.

#### Scenario: A projected change event reaches the router

- **WHEN** the database stream projects a change event
- **THEN** its resume token and routing fields remain available without fetching unnecessary full-document or update-description content

### Requirement: Change events invalidate affected cache entries

A routed insert, update, replace, delete, drop, `dropDatabase`, rename, or invalidation event SHALL invalidate affected cached identities or namespaces before a later hit.

#### Scenario: An external update is received

- **WHEN** an independent writer updates a cached document and the manager processes the corresponding change event
- **THEN** the manager invalidates that document and any affected result namespace before a later cache hit can return the old value

#### Scenario: A concurrent write has not reached the stream worker

- **WHEN** an independent writer commits an update while a healthy manager has not yet processed its change event
- **THEN** a concurrent cache hit is permitted to return the prior cached value, and the manager records no claim that stream health is a per-write catch-up barrier

#### Scenario: The database is dropped

- **WHEN** the manager processes a `dropDatabase` or its resulting invalidation event
- **THEN** it clears every cache namespace for that database, bypasses cache use while reopening the stream, and resumes only from a safe post-invalidation position

#### Scenario: A database-wide invalidation has unrelated namespaces

- **WHEN** the manager clears a database while the cache tracks namespaces from other databases
- **THEN** it enumerates and clears only the affected database's namespaces

### Requirement: Namespace and index events refresh cache metadata

Creation and index change events SHALL advance the relevant namespace metadata generations.

#### Scenario: A namespace is created after being absent

- **WHEN** the manager processes a `create` event for a namespace that has cached namespace-guarded entries admitted while it was absent
- **THEN** it advances that namespace's epoch and generation, so a collection-type or eligibility determination made before the namespace existed is treated as stale, and it physically reclaims those pre-existence entries rather than leaving them resident

#### Scenario: An index is created or dropped on a live collection

- **WHEN** the manager processes a `createIndexes` or `dropIndexes` event for a namespace
- **THEN** it routes the event to that namespace for consumers that track index metadata, without advancing the namespace's document-cache generation or epoch and without requiring a `documentKey`

### Requirement: Unsupported change-stream features disable caching

The manager SHALL require MongoDB 8.0 or newer and fail closed during startup if the server cannot support expanded change events.

#### Scenario: The server cannot provide expanded events

- **WHEN** the manager starts against a MongoDB server older than 8.0 or a server that rejects `show_expanded_events=True`
- **THEN** startup fails closed and the manager does not mark the cache eligible for hits or admission

### Requirement: Stream uncertainty bypasses cache reads

The manager SHALL bypass cache lookup and admission while its stream position is uncertain.

#### Scenario: Resume history is unavailable

- **WHEN** a disconnected stream cannot resume from its saved token
- **THEN** the manager clears the affected cache, bypasses cache use until a new stream is healthy, and records the recovery state

#### Scenario: A read spans stream recovery

- **WHEN** a read begins cache admission while its database stream is unavailable and the stream becomes healthy before the read completes
- **THEN** the completed read is not admitted to the cache

### Requirement: Shutdown terminates recovery and cleanup

Stopping the manager SHALL prevent recovery from reopening streams and SHALL report cleanup failures.

#### Scenario: A stop races stream recovery

- **WHEN** a stop request races a successful stream reopen
- **THEN** the supervisor finishes stopped and cache use for its database remains bypassed

#### Scenario: Shutdown blocks on cleanup

- **WHEN** a supervisor's stream or worker cleanup blocks during shutdown
- **THEN** cache use for its database is bypassed before cleanup completes

### Requirement: Sync and asyncio recovery are equivalent

The synchronous worker and asyncio task SHALL implement equivalent startup, shutdown, retry, resume, and clear-on-uncertainty semantics.

#### Scenario: A resumable interruption occurs

- **WHEN** a temporary stream interruption occurs with resumable history available
- **THEN** each execution model reconnects with the saved token and restores cache eligibility only after recovery succeeds

#### Scenario: Shutdown is in progress

- **WHEN** synchronous or asyncio shutdown waits for stream cleanup
- **THEN** each execution model bypasses cache use throughout that wait

### Requirement: Managers use one measured await-time default

Synchronous and asynchronous managers SHALL use the same documented default `max_await_time_ms` selected from retained measurements.

#### Scenario: A manager uses the measured default

- **WHEN** a caller creates a manager without an await-time override
- **THEN** every stream it opens uses the documented measured default

### Requirement: Managers apply a validated await-time override

Each manager SHALL accept a positive integer millisecond override in the supported wire-command range and apply it to opened and reopened streams. Boolean values SHALL be rejected as invalid, along with other invalid values, at manager construction.

#### Scenario: Managers require different await times

- **WHEN** a caller creates two managers with different valid overrides in one process
- **THEN** each manager uses its own value for both initial and reopened streams

#### Scenario: An invalid value is supplied

- **WHEN** a caller supplies a boolean, zero, a negative value, a non-integer value, or a value outside the supported range
- **THEN** manager construction fails before opening a stream

### Requirement: Await time is not configured from the environment

The library SHALL NOT read a process environment variable for `max_await_time_ms`.

#### Scenario: An environment variable is set

- **WHEN** a process environment variable names a different await time but the caller supplies no override
- **THEN** the manager uses its documented default

### Requirement: Await-time guidance explains timeout limits

Public guidance SHALL describe `max_await_time_ms` as an upper bound on an idle `getMore` wait, not a guaranteed bound on event delivery or failure detection, and explain its interaction with PyMongo timeout settings.

#### Scenario: A caller chooses an await-time override

- **WHEN** the caller reads the manager argument documentation
- **THEN** it distinguishes idle `getMore` waiting from delivery and failure-detection latency and points out the relevant PyMongo timeout settings

### Requirement: Explicit barriers prove applied invalidations

A manager SHALL provide an opt-in database-scoped barrier for a validated causal write boundary. Successful return SHALL prove that every relevant invalidation through that boundary has been applied to that manager before subsequent cache hits or admissions can use pre-invalidation state. Receiving an event, storing a resume position, observing a healthy stream, or seeing one event at the boundary's timestamp SHALL NOT alone establish success. The guarantee SHALL cover single-document and query-result invalidation and SHALL NOT cover writes beyond the supplied boundary, other managers, or future independent writers.

#### Scenario: A write changes a cached document and a query result

- **WHEN** a caller supplies a valid completed-write boundary affecting a cached identity and a cached collection query
- **THEN** successful barrier return means both affected pre-write cache entries have been invalidated in that manager

#### Scenario: Several events share the boundary timestamp

- **WHEN** several relevant events share a timestamp and only some have been applied
- **THEN** the barrier does not report success based on the first applied event at that timestamp

#### Scenario: A transaction changes multiple collections

- **WHEN** a supported committed transaction establishes a valid boundary and changes multiple collections in the named database
- **THEN** successful barrier return covers all relevant invalidations in that database through the committed boundary

#### Scenario: A read spans invalidation

- **WHEN** a read captured pre-invalidation state and finishes after the barrier's relevant invalidations have been applied
- **THEN** its old generation cannot be admitted as a valid cache entry after successful barrier return

#### Scenario: A later writer remains independent

- **WHEN** an independent write occurs beyond a successfully completed barrier's boundary
- **THEN** ordinary cached reads retain their documented eventual behavior for that later write

### Requirement: Barrier inputs have verifiable provenance

A barrier SHALL validate its database/deployment scope and completed-write provenance before accepting a boundary. It SHALL reject unacknowledged writes, uncommitted transaction boundaries, missing operation information, foreign deployment scope, and any input whose relationship to applied stream progress cannot be established. It SHALL NOT infer a specific write boundary solely from wall time, an unrelated observed cluster time, or a consumer-library method's successful return.

#### Scenario: A write has an explicit supported boundary

- **WHEN** an acknowledged completed write provides a supported verifiable boundary for the manager's deployment
- **THEN** the barrier can use that immutable boundary without concurrently sharing the application's live session with its worker

#### Scenario: An upstream consumer hides its boundary

- **WHEN** a library completes a raw write but supplies no information establishing a supported causal boundary
- **THEN** the manager does not claim to recognize that specific write automatically, and public guidance states the unsupported boundary acquisition case

#### Scenario: A sharded cluster commits a cross-shard transaction

- **WHEN** an application captures a boundary after committing a transaction that spans shards of a sharded cluster
- **THEN** public guidance states that this boundary is unsupported, because change events of that transaction can follow the session's operation time

#### Scenario: A transaction is still open

- **WHEN** an input describes operations in an uncommitted transaction
- **THEN** the barrier rejects it rather than reporting the operations invalidated

### Requirement: Barrier lifecycle is bounded and explicit

Every barrier call SHALL have an explicit finite positive timeout and one monotonic deadline covering activation, progress acquisition, waiting, and recovery. Timeout, unsupported startup, closed management, or loss of the required continuity SHALL produce an explicit unsuccessful outcome rather than success inferred from local clearing. Cancellation SHALL release call-specific resources without stopping a shared healthy stream. Pending waits SHALL be released unsuccessfully during manager shutdown. Synchronous and asyncio barriers SHALL provide equivalent guarantees and failure semantics.

#### Scenario: A quiet database reaches a supported boundary

- **WHEN** a supported write or no-op boundary has been passed with no later relevant event
- **THEN** the barrier can establish completion using its proven progress mechanism without requiring an unrelated application write

#### Scenario: The deadline expires during startup

- **WHEN** stream activation or boundary acquisition consumes the call's deadline
- **THEN** the call terminates unsuccessfully within its documented timeout/cleanup bounds rather than starting another full waiting interval

#### Scenario: Resume history is lost

- **WHEN** the stream loses continuity needed to prove a pending boundary
- **THEN** the pending call fails explicitly rather than treating cache clearing and a new healthy stream as proof that the old boundary was applied

#### Scenario: A boundary precedes recovered continuity

- **WHEN** a barrier starts after a history loss with a boundary that precedes the recovered stream
- **THEN** the call fails explicitly instead of completing because the recovered stream has passed the boundary

#### Scenario: A waiter is cancelled

- **WHEN** one asyncio barrier waiter is cancelled while other waits share the stream
- **THEN** its retained waiter state is released and the other waits and shared stream remain operational

#### Scenario: Shutdown races a pending wait

- **WHEN** the manager closes before a pending barrier establishes completion
- **THEN** the wait is released with an explicit closed outcome and no recovery can reopen a stream for it

### Requirement: Barriers do not synchronize ordinary reads

Ordinary cached reads SHALL retain the existing eventual coherency contract without an implicit per-read causal wait. Barrier state SHALL retain progress per watched database and outstanding calls, not an unbounded history of application writes. Barriers SHALL NOT automatically write marker data or decode opaque resume tokens to manufacture a proof.

#### Scenario: An application does not request a barrier

- **WHEN** an application performs ordinary cached reads without the opt-in operation
- **THEN** those reads do not issue barrier requests or wait for a causal boundary

#### Scenario: A long-lived application completes many barriers

- **WHEN** an application repeatedly completes or cancels barrier calls
- **THEN** completed-call and per-write history does not accumulate in manager memory
