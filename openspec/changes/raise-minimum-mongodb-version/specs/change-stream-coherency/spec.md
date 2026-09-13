## MODIFIED Requirements

### Requirement: A manager owns one database-scoped invalidation stream

For every active cached database, the manager SHALL use exactly one database-scoped stream opened with `show_expanded_events=True` to route insert, update, replace, delete, drop, `dropDatabase`, rename, `create`, and invalidation events to all affected cache namespaces. The manager SHALL require MongoDB server version 8.0 or newer and SHALL fail closed during startup when the server cannot support the expanded-events option. The stream projection SHALL retain the resume token and fields required for routing while omitting unnecessary full documents and update descriptions. A `create` event SHALL advance the affected namespace's epoch and generation and SHALL physically reclaim any entries cached against that namespace while it did not yet exist, the same as a clear, so a namespace coming into existence invalidates any determination a caller made about it before it existed and does not leave pre-existence entries consuming shared budget. Database-wide invalidation SHALL enumerate only namespaces registered for the affected database and SHALL not traverse namespace metadata for other databases.

#### Scenario: An external update is received

- **WHEN** an independent writer updates a cached document and the manager processes the corresponding change event
- **THEN** the manager invalidates that document and any affected result namespace before a later cache hit can return the old value

#### Scenario: A concurrent write has not reached the stream worker

- **WHEN** an independent writer commits an update while a healthy manager has not yet processed its change event
- **THEN** a concurrent cache hit is permitted to return the prior cached value, and the manager records no claim that stream health is a per-write catch-up barrier

#### Scenario: The database is dropped

- **WHEN** the manager processes a `dropDatabase` or its resulting invalidation event
- **THEN** it clears every cache namespace for that database, bypasses cache use while reopening the stream, and resumes only from a safe post-invalidation position

#### Scenario: The server cannot provide expanded events

- **WHEN** the manager starts against a MongoDB server older than 8.0 or a server that rejects `show_expanded_events=True`
- **THEN** startup fails closed and the manager does not mark the cache eligible for hits or admission

#### Scenario: A client caches multiple databases

- **WHEN** a caller activates cached collections in more than one database through the same client
- **THEN** the manager maintains one independent database-scoped stream for each active cached database, and an event in one database cannot be routed as an invalidation for another database

#### Scenario: A database-wide invalidation has unrelated namespaces

- **WHEN** the manager clears a database while the cache tracks namespaces from other databases
- **THEN** it enumerates and clears only the affected database's namespaces

#### Scenario: A namespace is created after being absent

- **WHEN** the manager processes a `create` event for a namespace that has cached namespace-guarded entries admitted while it was absent
- **THEN** it advances that namespace's epoch and generation, so a collection-type or eligibility determination made before the namespace existed is treated as stale, and it physically reclaims those pre-existence entries rather than leaving them resident
