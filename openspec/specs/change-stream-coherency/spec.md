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

### Requirement: Database stream health is locally inspectable

Both execution models SHALL expose an immutable, synchronous health observation for a named database. The observation SHALL distinguish a stream that has not started, a connection in progress, healthy operation, reconnection, unsuccessful startup, and closed management. Inspection SHALL NOT activate a database or perform database I/O. Startup failures SHALL remain observable until superseded by a later attempt or manager closure. Health observations SHALL contain no credentials, application data, exception text, or resume positions, and SHALL NOT assert per-write catch-up.

#### Scenario: An application inspects an untouched database

- **WHEN** a caller requests health for a database the manager has never activated
- **THEN** the result reports that no stream has started and inspection does not create one

#### Scenario: Stream startup fails

- **WHEN** a cached read cannot establish a database stream and the caller subsequently inspects that database
- **THEN** inspection reports unsuccessful startup even though no healthy supervisor was retained

#### Scenario: A later startup succeeds

- **WHEN** a later read successfully starts a previously failed database stream
- **THEN** subsequent health observations report its current state rather than retaining the earlier failure

#### Scenario: Stream recovery is active

- **WHEN** a stream is reconnecting after an interruption
- **THEN** health inspection distinguishes reconnection from healthy operation and cached reads retain the existing uncertainty bypass behavior

#### Scenario: The manager is closed

- **WHEN** a caller inspects any database after manager closure
- **THEN** the observation reports closed management without reopening a stream

#### Scenario: A healthy stream has not processed a concurrent write

- **WHEN** a healthy stream is inspected before it processes an independent writer's event
- **THEN** the observation reports health without claiming that the writer's invalidation has been applied
