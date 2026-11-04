# Spec Delta

## MODIFIED Requirements

### Requirement: Unresolved unique-key reads use namespace guards

A unique-key read without a resolved alias SHALL capture namespace generation before its origin read. Admission SHALL reject results invalidated since that capture. A match SHALL use the configured unique-key retention policy; a negative result SHALL retain namespace protection. Choosing an identity-backed representation SHALL NOT bypass the captured namespace-generation check.

#### Scenario: A unique-key value is looked up for the first time

- **WHEN** a caller reads by a unique key with no existing alias for that key value
- **THEN** the facade captures namespace generation before the read and admits the match using the configured pair or namespace policy only if that capture remains valid
- **AND** a retained negative result uses a namespace-guarded key containing the unique-key definition, value and read shape

### Requirement: First unique-key matches admit an identity entry

An eligible first-time unique-key match SHALL use the configured retention policy. With the count limit disabled, it SHALL retain the existing namespace-value, identity-value and alias targets, subject to any configured key checks. With the count limit enabled, it SHALL prefer the valid identity-value/alias pair and use the original namespace-result fallback when the pair cannot be admitted.

#### Scenario: A first-time match also admits an identity-guarded entry

- **WHEN** a caller reads by a unique key with no existing alias, the read matches a document, and the count limit is disabled
- **THEN** the facade keeps the existing namespace and identity admission targets, subject to eligibility and key limits, with a published alias backed by valid identity state

#### Scenario: A resolved unique-key alias is read again

- **WHEN** a caller reads by a unique key whose alias was already resolved by an earlier read
- **THEN** a valid matching identity entry can serve the read under its identity-generation and namespace-epoch guards
- **AND** an origin miss verifies the original predicate using a namespace capture before publishing the configured retained representation

#### Scenario: A one-slot fallback is read again

- **WHEN** a count-enabled unique-key read retained the original namespace result because its pair could not fit
- **THEN** a repeated query can hit that valid fallback with one hit and no miss, without needing a newly admitted identity value or alias

### Requirement: Resolved aliases are reverified on cache misses

A resolved unique-key read SHALL verify its original predicate against MongoDB when neither a valid matching identity entry nor a count-enabled namespace fallback serves the read. A fallback hit SHALL preserve the existing single-read outcome contract. An identity miss alone SHALL NOT force origin execution when a valid fallback exists.

#### Scenario: A resolved alias is still accurate

- **WHEN** no valid retained representation serves a key value with a resolved alias, and an origin query by the original predicate matches the identity the alias recorded
- **THEN** the facade confirms the relationship and admits or refreshes the configured pair or namespace representation according to its limits

#### Scenario: A resolved alias has gone stale

- **WHEN** no valid retained representation serves a key value with a resolved alias, and an origin query by the original predicate matches a different identity or no document
- **THEN** the facade does not return or cache a value based on the stale identity; it discards or re-resolves the alias and admits the actual outcome under the configured policy

#### Scenario: An alias exists but only the namespace fallback can serve this shape

- **WHEN** a resolved alias has no valid identity entry for the requested read shape but the count-enabled namespace fallback remains valid
- **THEN** the fallback serves the read without an origin query, with one hit and no miss
