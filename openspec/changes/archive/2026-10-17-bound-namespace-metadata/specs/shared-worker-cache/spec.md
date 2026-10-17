# Spec Delta

## MODIFIED Requirements

### Requirement: Stable collection deployment

Shared caches SHALL support collection-name churn without unbounded namespace metadata. Collection drops SHALL release owner namespace slots. When all configured slots are occupied, reads for additional namespaces SHALL preserve MongoDB behavior and bypass shared caching until a slot is released. Guidance SHALL explain sizing, reclamation and capacity bypass.

#### Scenario: Deployment sizing

- **WHEN** an operator configures the server for an application
- **THEN** `namespaces` limits simultaneous tracked database/collection pairs, dropped collections release slots, and names beyond capacity bypass shared caching

#### Scenario: Shared namespace capacity is exhausted

- **WHEN** a read targets a new namespace while every configured shared slot is assigned
- **THEN** the read completes through MongoDB without retaining metadata for that namespace

## ADDED Requirements

### Requirement: Worker namespace metadata is bounded

Each shared worker SHALL retain no more than the configured `namespaces` count in its local namespace metadata and slot maps. Each map SHALL evict its oldest stored entry when its capacity is reached.

#### Scenario: A worker sees more names than its configured capacity

- **WHEN** a worker accesses more distinct namespace names than `namespaces`
- **THEN** both local maps remain within the configured capacity and evicted names can refresh metadata later

### Requirement: Reused shared slots reject stale readers

Reusing a shared namespace slot SHALL advance its epoch so captures and local readers holding the prior assignment cannot observe entries published for the new namespace. Owner restart SHALL continue to fence readers by owner incarnation.

#### Scenario: A stale worker holds a recycled slot

- **WHEN** a namespace slot is reassigned while a worker retains the old namespace epoch
- **THEN** the reader rejects the stale lookup and cannot return the new namespace's value

#### Scenario: The owner restarts after slot reuse

- **WHEN** the shared owner restarts while workers retain previous namespace slots
- **THEN** those slots are unusable under the new owner incarnation until refreshed
