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
