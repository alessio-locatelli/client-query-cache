# Spec Delta

## ADDED Requirements

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
