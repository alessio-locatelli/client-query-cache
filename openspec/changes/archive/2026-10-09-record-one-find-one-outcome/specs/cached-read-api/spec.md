# Spec Delta

## ADDED Requirements

### Requirement: A single-document read records one cache outcome

An eligible single-document read SHALL record at most one hit or miss, including a read that discovers unique-key metadata. A read served from the cache SHALL record one hit and no miss. A read that completes without a hit or bypass SHALL record one miss. Existing bypass accounting, including stream-unavailable bypasses, SHALL be preserved.

#### Scenario: A cold read matches a unique index

- **WHEN** an eligible single-document read matches a unique index in a namespace whose unique-key metadata has not been discovered, and no cached result exists
- **THEN** misses increase by one and hits are unchanged

#### Scenario: A cold read matches no unique index

- **WHEN** an eligible single-document read in a namespace whose unique-key metadata has not been discovered matches no unique index, or metadata discovery fails, and no cached result exists
- **THEN** misses increase by one and hits are unchanged

#### Scenario: A cached generic result is reused before metadata discovery

- **WHEN** an eligible single-document read finds a valid cached generic result while the namespace's unique-key metadata is unknown
- **THEN** hits increase by one, misses are unchanged, and the read does not query index metadata
