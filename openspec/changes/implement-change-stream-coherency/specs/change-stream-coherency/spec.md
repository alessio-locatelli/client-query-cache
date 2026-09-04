## Purpose

This capability keeps a process-local cache safe to use only while a database-scoped MongoDB change stream can establish or restore known invalidation continuity.

## ADDED Requirements

### Requirement: A manager owns one database-scoped invalidation stream
For every active cached database, the manager SHALL use one stream to route insert, update, replace, delete, drop, `dropDatabase`, rename, and invalidation events to all affected cache namespaces. The stream projection SHALL retain the resume token and fields required for routing while omitting unnecessary full documents and update descriptions.

#### Scenario: An external update is received
- **WHEN** an independent writer updates a cached document and the manager processes the corresponding change event
- **THEN** the manager invalidates that document and any affected result namespace before a later cache hit can return the old value

#### Scenario: A concurrent write has not reached the stream worker
- **WHEN** an independent writer commits an update while a healthy manager has not yet processed its change event
- **THEN** a concurrent cache hit is permitted to return the prior cached value, and the manager records no claim that stream health is a per-write catch-up barrier

#### Scenario: The database is dropped
- **WHEN** the manager processes a `dropDatabase` or its resulting invalidation event
- **THEN** it clears every cache namespace for that database, bypasses cache use while reopening the stream, and resumes only from a safe post-invalidation position

### Requirement: Cache use fails closed during stream uncertainty
The manager SHALL permit cache use only after stream startup establishes the documented healthy state. During recovery it SHALL bypass cache admission and hits. If continuity cannot be resumed, it SHALL clear the affected cache before re-establishing the stream.

#### Scenario: Resume history is unavailable
- **WHEN** a disconnected stream cannot resume from its saved token
- **THEN** the manager clears the affected cache, bypasses cache use until a new stream is healthy, and records the recovery state

### Requirement: Sync and asyncio recovery are equivalent
The synchronous worker and asyncio task SHALL implement equivalent startup, shutdown, retry, resume, and clear-on-uncertainty semantics.

#### Scenario: A resumable interruption occurs
- **WHEN** a temporary stream interruption occurs with resumable history available
- **THEN** each execution model reconnects with the saved token and restores cache eligibility only after recovery succeeds
