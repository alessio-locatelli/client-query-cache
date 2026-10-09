# Spec Delta

These production changes apply only if the shared-cache investigation promotes an implementation.

## MODIFIED Requirements

### Requirement: Managers use one invalidation stream per database

A standalone manager SHALL use one database-scoped change stream for each database it caches. An explicitly attached shared worker group SHALL instead own one such stream per active cached database, without additional invalidation cursors in its workers. All streams SHALL use `show_expanded_events=True`.

#### Scenario: A client caches multiple databases

- **WHEN** a caller activates cached collections in more than one database through the same client
- **THEN** its standalone manager or attached group maintains one independent database-scoped stream for each active cached database, and an event in one database cannot be routed as an invalidation for another database

#### Scenario: Workers activate the same database concurrently

- **WHEN** several attached workers activate cached reads against the same database
- **THEN** one group activation owns its stream and competing requests bypass while startup is pending, without opening worker-local watches

#### Scenario: Distinct authorized groups cache the same database

- **WHEN** isolated groups cache the same database name
- **THEN** each group owns its own stream and state without combining different security scopes

## ADDED Requirements

### Requirement: Shared stream health identifies replicated observations

An attached manager's local stream-health observation SHALL identify its group scope, coordinator incarnation and observation age. Missing or expired observations SHALL NOT appear as current healthy readiness. Inspection SHALL remain synchronous and SHALL NOT activate a stream or perform remote I/O.

#### Scenario: A previously healthy coordinator disappears

- **WHEN** an attached worker inspects health after its replicated observation expires
- **THEN** it sees unavailable or expired health without treating the last healthy observation as current readiness
