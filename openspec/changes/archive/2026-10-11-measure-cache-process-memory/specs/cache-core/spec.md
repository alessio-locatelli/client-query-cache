# Spec Delta

## ADDED Requirements

### Requirement: Resident entries share namespace identity

Resident entries and their physical keys SHALL reference one namespace identifier per registered namespace instead of retaining a separate equal identifier for each admission. Sharing SHALL NOT change key equality, eviction, reclamation, or lookup outcomes.

#### Scenario: Entries admitted through different requests

- **WHEN** several reads of one namespace, each supplying its own equal namespace identifier, are admitted as identity-guarded and namespace-guarded entries
- **THEN** every resident entry and physical key references the same namespace identifier, and lookups through new equal identifiers still hit

### Requirement: Unaliased identities retain no alias storage

Identity bookkeeping SHALL retain alias storage only while at least one unique-key alias resolves to that identity. Alias publication, displacement, invalidation, pruning, and namespace reclamation SHALL keep their existing outcomes.

#### Scenario: An identity is cached without an alias

- **WHEN** an identity-guarded entry is admitted without a unique-key alias
- **THEN** its identity bookkeeping retains no alias storage of its own

#### Scenario: An alias moves to another identity

- **WHEN** an alias published for one identity is later published for another identity, or its identity is written or reclaimed
- **THEN** the alias resolves only to its current identity, and an identity left without aliases again retains no alias storage
