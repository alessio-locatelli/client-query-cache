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

Both execution models SHALL expose an immutable, synchronous health observation for a named database, distinguishing a stream that has not started, a connection in progress, healthy operation, reconnection, unsuccessful startup, and closed management. Startup failures SHALL remain observable until superseded by a later attempt or manager closure.

#### Scenario: An application inspects an untouched database

- **WHEN** a caller requests health for a database the manager has never activated
- **THEN** the result reports that no stream has started and inspection does not create one

#### Scenario: Stream connection is in progress

- **WHEN** a caller inspects a database while its stream connection is in progress
- **THEN** the observation distinguishes connecting from healthy operation

#### Scenario: Stream startup fails

- **WHEN** a cached read cannot establish a database stream and the caller subsequently inspects that database
- **THEN** inspection reports unsuccessful startup even though no healthy supervisor was retained
- **AND** the failure remains observable until a later attempt or manager closure supersedes it

#### Scenario: A later startup succeeds

- **WHEN** a later read successfully starts a previously failed database stream
- **THEN** subsequent health observations report its current state rather than retaining the earlier failure

#### Scenario: Stream recovery is active

- **WHEN** a stream is reconnecting after an interruption
- **THEN** health inspection distinguishes reconnection from healthy operation and cached reads retain the existing uncertainty bypass behavior

#### Scenario: The manager is closed

- **WHEN** a caller inspects any database after manager closure
- **THEN** the observation reports closed management without reopening a stream

### Requirement: Database health inspection is local and read-only

Database health inspection SHALL NOT activate a database or perform database I/O.

#### Scenario: Repeated database health inspection

- **WHEN** a caller inspects a named database repeatedly
- **THEN** inspection performs no database I/O and does not activate that database

### Requirement: Database health observations expose no sensitive data

Database health observations SHALL contain no credentials, application data, exception text, or resume positions.

#### Scenario: A caller inspects a failed database stream

- **WHEN** a caller inspects health after stream startup fails
- **THEN** the observation includes no credentials, application data, exception text, or resume positions

### Requirement: Database health does not assert write catch-up

Database health observations SHALL NOT assert per-write catch-up.

#### Scenario: A healthy stream has not processed a concurrent write

- **WHEN** a healthy stream is inspected before it processes an independent writer's event
- **THEN** the observation reports health without claiming that the writer's invalidation has been applied

### Requirement: Initial stream failures have a retry cooldown

Each database SHALL retain an initial-startup retry deadline after failure. Before that deadline, reads SHALL bypass caching without starting another stream, waiting for the deadline, or emitting another startup warning. A later read at or after the deadline SHALL permit one new attempt. These rules SHALL apply equally to unsupported servers, watch-permission failures, and transient startup failures.

#### Scenario: Reads arrive during cooldown

- **WHEN** multiple eligible reads target a database before its failed startup's retry deadline
- **THEN** they execute uncached with no additional version checks or stream-open attempts attributable to activation
- **AND** health remains `startup_failed` and ordinary bypasses retain the `stream_unavailable` reason

#### Scenario: A retry becomes eligible

- **WHEN** a read arrives at or after the deadline
- **THEN** one new startup attempt is permitted without a timer or background startup retry
- **AND** success restores normal caching eligibility while another failure sets a new deadline

#### Scenario: The failure is persistent

- **WHEN** startup repeatedly fails because the server lacks required features or watch permissions
- **THEN** the same cooldown policy limits repeated attempts and warnings without permanently disabling later recovery

### Requirement: Startup retry delays are bounded and increasing

Initial retry delays SHALL use exponential caps starting at 100 milliseconds, doubling to at most 30 seconds, with each delay sampled between half its cap and the cap. Deadline comparisons SHALL use a monotonic clock. Successful startup SHALL discard its startup retry history. Established-stream reconnect behavior SHALL retain its existing policy.

#### Scenario: Successive initial attempts fail

- **WHEN** successive initial startup attempts fail
- **THEN** their delay caps are 100, 200, 400 milliseconds and continue doubling to a maximum of 30 seconds
- **AND** each delay is positive and no greater than 30 seconds

### Requirement: Database startups do not serialize unrelated activation

Activation SHALL perform database I/O without holding a coordinator-wide lock. At most one startup attempt SHALL be in progress for each database. Reads encountering that database's pending activation SHALL bypass caching without waiting for the startup. Activation and use of another database SHALL be able to proceed independently.

#### Scenario: Two databases activate concurrently

- **WHEN** startup for database A is blocked in network I/O and a read activates database B
- **THEN** B can finish startup before A is released

#### Scenario: An established database is read during another startup

- **WHEN** database A is starting and database B already has a healthy stream
- **THEN** B's reads can use its cache without waiting for A

#### Scenario: Several reads activate one database

- **WHEN** several reads reach a database whose initial attempt is still pending
- **THEN** exactly one attempt runs and the other reads bypass caching while health reports `connecting`

### Requirement: Pending activation owns public health reporting

An unpublished initial activation SHALL report `connecting` through public health inspection even after native startup succeeds. Live supervisor health SHALL become observable only after successful publication. Closed management SHALL take precedence over pending activation.

#### Scenario: Native startup succeeds before publication

- **WHEN** startup has succeeded internally but its owner has not yet published the supervisor
- **THEN** concurrent health inspection reports `connecting`, and competing reads continue to bypass caching

#### Scenario: Publication completes

- **WHEN** the owner completes publication of the successfully started supervisor
- **THEN** subsequent health inspection reports its current supervision state

#### Scenario: Closure wins the publication race

- **WHEN** closure begins after native startup succeeds but before publication
- **THEN** health inspection reports `closed` and the late attempt cannot expose `healthy`

### Requirement: Closing owns pending stream activation

Closure SHALL reject new activation and make all tracked databases unavailable before waiting for cleanup. Async closure SHALL establish this state before its first suspension, independently of cleanup task scheduling. Pending startups SHALL remain owned until their native resources and workers are released. An attempt finishing after closure begins SHALL NOT publish a usable stream or restore cache availability. Closure SHALL release retained retry state.

#### Scenario: Close races a successful startup

- **WHEN** closure begins while a stream-open operation is pending and that operation subsequently succeeds
- **THEN** its stream is closed, no worker remains running after closure completes, and the database remains unavailable

#### Scenario: Cleanup for one database blocks

- **WHEN** shutdown waits for database A's worker while database B is tracked
- **THEN** B is already unavailable even if its cleanup has not yet completed

#### Scenario: Activation runs before the async cleanup task

- **WHEN** async closure reaches its first suspension and an already-ready activation runs before the retained cleanup task begins executing
- **THEN** activation raises the existing closed-coordinator lifecycle error without starting a supervisor or opening a stream
- **AND** public health reports `closed` and all tracked databases are already unavailable

### Requirement: Async shutdown cleanup survives caller cancellation

Async closure SHALL finish its owned resource cleanup before propagating caller cancellation. Concurrent and subsequent closure calls SHALL join the same cleanup without duplicating it. Manager-owned cache release SHALL also complete before cancellation propagates.

#### Scenario: The shutdown caller is cancelled during cleanup

- **WHEN** native stream cleanup is blocked and the caller executing async closure is cancelled
- **THEN** cleanup remains active and the caller does not finish before it
- **AND** after native cleanup is released, streams and workers are released before cancellation propagates

#### Scenario: Other callers close during or after cancelled shutdown

- **WHEN** another caller closes while cancellation-resistant cleanup is pending, or after it finishes
- **THEN** it joins or observes that same cleanup result without skipping unfinished cleanup or starting duplicate native close operations

#### Scenario: Cancellation is requested repeatedly

- **WHEN** the shutdown caller is cancelled again while waiting for cleanup
- **THEN** owned cleanup still finishes before that caller propagates cancellation

#### Scenario: A manager shutdown caller is cancelled

- **WHEN** manager closure is cancelled during coordinator cleanup
- **THEN** the manager's cache is released after coordinator cleanup and before cancellation propagates

### Requirement: Interrupted activation releases its reservation

Async cancellation and unexpected startup exceptions SHALL propagate after releasing activation ownership and cleaning any opened native resources. They SHALL NOT leave a database permanently connecting, publish a usable stream, or overwrite closed management. Cancellation SHALL NOT count as a failed startup retry attempt.

#### Scenario: Async activation is cancelled

- **WHEN** the startup-owning caller is cancelled before startup completes
- **THEN** its resources are cleaned and another read can initiate startup if the manager remains open
- **AND** health reports `startup_failed` until another attempt and no cooldown is imposed by cancellation

#### Scenario: An unexpected exception interrupts activation

- **WHEN** startup raises an exception outside the supported startup-failure boundary
- **THEN** the original exception propagates, the reservation is released, and a subsequent read can try again

### Requirement: Startup guidance distinguishes retries from freshness

Public operations guidance SHALL describe initial retry cooldown, read-driven recovery, startup and reconnection health observations, and uncached fallback. It SHALL distinguish these states from event catch-up and direct users to native reads when freshness is required.

#### Scenario: An operator diagnoses unavailable caching

- **WHEN** an operator follows startup-failure guidance
- **THEN** the guide explains the warning, `startup_failed`, `stream_unavailable`, subsequent `connecting` and `healthy`, and why reads continue uncached between attempts
