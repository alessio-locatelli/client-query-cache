# Spec Delta

## ADDED Requirements

### Requirement: Adoption guidance connects workload decisions to canonical contracts

Public documentation SHALL provide a concise adoption guide linking consistency, cache eligibility, supported environments, and deployment costs. It SHALL compare appropriate uses of indexed database reads, process-local caching, shared caches, HTTP caching, and edge caching without unsupported performance rankings.

#### Scenario: An application developer evaluates adoption

- **WHEN** a reader opens the adoption guide
- **THEN** they can identify freshness and process-model constraints and follow canonical references before choosing a caching layer

### Requirement: Eligibility guidance pairs operations with observable outcomes

Public guidance SHALL pair short operations with public counter observations for a miss, a hit, an oversized result, a session-bound read, unsupported cursor options, and a nondeterministic aggregation. It SHALL distinguish ordinary bypasses, oversized recordings, and direct reads.

#### Scenario: A reader investigates an uncached result

- **WHEN** a reader follows the eligibility exercise on a supported disposable deployment
- **THEN** they can distinguish each listed outcome using snapshot differences without private APIs

### Requirement: Permission recovery guidance states observable boundaries

Public operations guidance SHALL describe a disposable database change-stream permission-denial and restoration exercise using public stream-health and cache snapshots. It SHALL distinguish cache bypass from database availability and link canonical retry policy without promising fixed recovery times.

#### Scenario: Reads are permitted but watching the database is denied

- **WHEN** a reader follows the exercise
- **THEN** the guide identifies startup warnings, startup_failed health, stream_unavailable bypasses, and read-triggered recovery after permissions are restored

### Requirement: Upgrade guidance distinguishes reproducibility from compatibility

Public installation guidance SHALL recommend reproducible dependency selection and testing PyMongo upgrades before deployment, explain that driver integration can be sensitive to upgrades, and SHALL NOT claim that lockfiles or passing CI guarantee compatibility.

#### Scenario: An adopter updates PyMongo

- **WHEN** a reader follows the upgrade guidance
- **THEN** they retain reproducible versions and verify their application's cached reads, bypasses, lifecycle, and recovery before deploying the update
