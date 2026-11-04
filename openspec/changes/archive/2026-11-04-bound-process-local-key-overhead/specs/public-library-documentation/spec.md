# Spec Delta

## ADDED Requirements

### Requirement: Retention safeguard guidance states its bounds

The API reference SHALL document optional retention limits, validation, snapshot fields, count-enabled unique-key pair/fallback admission and separate decline counts without redefining bypasses. Deployment guidance SHALL give a configuration example, explain alias capacity and distinguish accounted key size from memory. It SHALL exclude in-flight requests, decoded results, opaque scalar referents and allocator retention from the guarantee and SHALL NOT promise an RSS ceiling.

#### Scenario: An operator configures the safeguard

- **WHEN** an operator follows the API reference and deployment guidance
- **THEN** they can enable each limit independently, interpret pair/fallback admission and decline counts separately from bypasses, and identify what remains outside the limits

#### Scenario: An operator chooses a small count limit

- **WHEN** they read the unique-key admission guidance
- **THEN** it explains a one-slot namespace fallback and a two-slot identity-plus-alias example, plus an occupied-cache example where an alias cannot displace an extra unrelated value
- **AND** it states that a key limit alone does not enable this policy

#### Scenario: An operator compares memory evidence

- **WHEN** they read current qualification results beside historical process-memory results
- **THEN** versions, configuration, occupancy and workload conditions identify which observations apply, without presenting historical measurements as current native-cache guarantees
