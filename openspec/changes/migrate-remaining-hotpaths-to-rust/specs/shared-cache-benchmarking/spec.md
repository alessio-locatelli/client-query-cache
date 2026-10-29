# Spec Delta

## ADDED Requirements

### Requirement: Native owner comparisons account for completed admission work

A native owner comparison SHALL account for worker and owner CPU through completed processing of measured admissions, including rejected and evicting admissions. It SHALL verify drained queues and stable residency before resource checkpoints and separately report foreground read latency, admission completion time, owner CPU, and group CPU per completed read. Returning earlier while deferring work SHALL NOT establish a CPU or memory saving.

#### Scenario: A worker returns while its admission remains queued

- **WHEN** the resource checkpoint is reached before the owner consumes that admission
- **THEN** the checkpoint is rejected until processing completes, and the intervening owner work remains in the measured resource scope

#### Scenario: Admission pressure triggers eviction or rejection

- **WHEN** the owner rejects entries or evicts resident entries during the registered workload
- **THEN** those operations remain in the accounting and both builds must match the registered outcomes

### Requirement: Scoped native owner replacements complete their delivery

A qualifying native owner replacement SHALL run through ordinary shared-manager construction and be retained in the same change, with its user-visible performance effect recorded in the changelog. Current-release qualification SHALL preserve the existing protocol's validity and recovery contract. A change to selection authority, fencing, or recovery semantics SHALL require a revised design decision before implementation; historical protocol claims still require their complete protocol.

#### Scenario: Owner bookkeeping improves without changing selection authority

- **WHEN** fresh matched evidence qualifies the integrated replacement
- **THEN** the same branch keeps it without a separate production-integration ticket

#### Scenario: A faster design removes authoritative selection

- **WHEN** the proposed implementation changes who validates a cold selection or capture
- **THEN** implementation pauses for the consequential design decision instead of treating the bookkeeping plan as authorization
