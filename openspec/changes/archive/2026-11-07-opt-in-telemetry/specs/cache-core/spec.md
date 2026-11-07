## MODIFIED Requirements

### Requirement: Cache health is inspectable

With telemetry enabled, the manager SHALL expose immutable health, capacity (including the configured `budget_bytes`), hit, miss, eviction, and bypass observations through publicly importable result types, without returning document values, queries, credentials, or resume tokens.

#### Scenario: An application inspects the manager

- **GIVEN** telemetry is enabled
- **WHEN** an application requests a cache inspection snapshot
- **THEN** it receives immutable lifecycle, capacity (including the configured `budget_bytes`), hit, miss, eviction, and bypass observations in publicly importable result types, without document values, queries, credentials, or resume tokens

### Requirement: Manager inspection is synchronous and read-only

With telemetry enabled, both execution models SHALL provide synchronous, local manager inspection that performs no database I/O, starts no stream, resets no counter, and changes no cache state.

#### Scenario: An asyncio application inspects statistics

- **GIVEN** telemetry is enabled
- **WHEN** an application requests a snapshot from an asyncio manager
- **THEN** it receives an immutable result synchronously without awaiting or performing database I/O

#### Scenario: Repeated inspection is read-only

- **GIVEN** telemetry is enabled
- **WHEN** an application inspects a manager repeatedly, including after close
- **THEN** inspection exposes the available lifecycle/statistics observations without reopening streams or resetting cumulative counters

### Requirement: Advanced cache inspection remains available

With telemetry enabled, the advanced cache inspection interface SHALL remain available with measurements equivalent to manager inspection.

#### Scenario: An advanced caller inspects the cache

- **GIVEN** telemetry is enabled
- **WHEN** a caller uses the advanced cache inspection interface
- **THEN** it exposes equivalent cache measurements for the same underlying state
