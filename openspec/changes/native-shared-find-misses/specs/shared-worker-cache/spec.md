## ADDED Requirements

### Requirement: Shared find preparation reuses portable query encodings

Shared find key preparation SHALL traverse a query family at most once when both exact local lookup and owner selection need encodings. The resulting keys SHALL preserve existing wire bytes, scalar distinctions, errors and owner selection behavior. Reuse SHALL remain bounded; oversized encodings SHALL remain usable without retention.

#### Scenario: A local miss selects through the owner

- **WHEN** an eligible shared find misses its exact local lookup
- **THEN** owner selection reuses the prepared family encoding without traversing the query again
- **AND** exact, covering and unlimited reuse retain their existing results

#### Scenario: A limit has a specialized integer representation

- **WHEN** a find uses a negative or BSON Int64 limit
- **THEN** its exact key and owner request retain the existing representation and selection semantics

#### Scenario: Portable keys exceed the retention bound

- **WHEN** a valid query produces keys larger than the key-cache retention bound
- **THEN** the current read can use those keys without retaining them or repeating query serialization

#### Scenario: A worker has no local index

- **WHEN** a worker cannot perform local lookup
- **THEN** it prepares only the existing owner-selection key and retains current admission and fallback behavior
