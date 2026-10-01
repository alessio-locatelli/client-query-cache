# Spec Delta

## MODIFIED Requirements

### Requirement: Cache health is inspectable

The manager SHALL expose immutable health, capacity, hit, miss, eviction, and bypass observations without returning document values, queries, credentials, or resume tokens. Both execution models SHALL provide a synchronous, local inspection method on the manager and publicly importable result types. Inspection SHALL NOT perform database I/O, start a stream, reset counters, or change cache state. The existing advanced cache inspection interface SHALL remain available with equivalent cache measurements.

#### Scenario: An application inspects the manager

- **WHEN** an application requests a cache inspection snapshot
- **THEN** it receives current lifecycle and capacity information without cached document contents

#### Scenario: An asyncio application inspects statistics

- **WHEN** an application requests a snapshot from an asyncio manager
- **THEN** it receives an immutable result synchronously without awaiting or performing database I/O

#### Scenario: Repeated inspection is read-only

- **WHEN** an application inspects a manager repeatedly, including after close
- **THEN** inspection exposes the available lifecycle/statistics observations without reopening streams or resetting cumulative counters

## ADDED Requirements

### Requirement: Bypass recording has fixed safe reasons

Every ordinary bypass recording SHALL increment the existing ordinary aggregate count and exactly one count from a fixed, publicly typed reason vocabulary. The vocabulary SHALL distinguish session-bound reads, incompatible read profiles, unsupported options, unsafe filters, unsafe projections, unsafe pipelines, uncanonicalizable keys, missing collections, views, time-series collections, unavailable metadata, unavailable streams, invalidated admissions, and unspecified advanced recording. A snapshot SHALL expose immutable reason counts whose sum equals its ordinary bypass aggregate. Oversized-result recordings SHALL remain separate and SHALL NOT increment ordinary reason counts. Existing recording-event semantics SHALL be preserved rather than redefined as one outcome per application request.

#### Scenario: A missing collection produces a bypass

- **WHEN** an otherwise eligible read targets a collection that does not exist
- **THEN** its ordinary bypass recording is classified as a missing collection rather than as an unhealthy stream or incompatible read profile

#### Scenario: A read has several bypass conditions

- **WHEN** a read is session-bound and also has unsupported options
- **THEN** its facade-level bypass recording has one session reason according to the documented precedence, rather than counting both conditions

#### Scenario: An admission loses continuity

- **WHEN** a previously eligible admission is declined because its availability generation changed while the database is currently available
- **THEN** the existing bypass recording is classified as an invalidated admission without claiming that the stream is currently unavailable

#### Scenario: A result exceeds the entry limit

- **WHEN** a cache admission is declined because its encoded result is oversized
- **THEN** the oversized count increments without incrementing the ordinary bypass aggregate or any ordinary reason

#### Scenario: Concurrent recordings and inspection

- **WHEN** bypass recordings race snapshot creation
- **THEN** each returned snapshot's ordinary reason counts sum to that snapshot's ordinary bypass aggregate, without promising a single atomic sample of independently observed capacity fields

#### Scenario: Advanced callers record an unspecified bypass

- **WHEN** an advanced caller uses the existing explicit bypass-recording interface without providing a reason
- **THEN** the call remains supported and increments the ordinary aggregate and the unspecified reason

### Requirement: Manager access preserves stream-cost inspection

Both manager execution models SHALL expose the existing per-database stream-cost snapshots and active-database discovery through synchronous, read-only manager accessors. Their measurement scope, cumulative counts, bounded lag samples, and clock limitations SHALL remain unchanged.

#### Scenario: A caller reads stream measurements through a manager

- **WHEN** a caller requests stream-cost measurements or active measurement databases through the manager
- **THEN** the observations agree with the existing advanced inspection source for the same underlying state, without additional database requests or state mutation
