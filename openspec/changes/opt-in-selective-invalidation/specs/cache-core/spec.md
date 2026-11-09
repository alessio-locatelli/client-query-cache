# Spec Delta

## MODIFIED Requirements

### Requirement: Namespace generations track writes and lifecycle events

Each MongoDB namespace SHALL track a monotonically increasing generation advanced by any write, clear, or creation. Ordinary namespace guards SHALL use this generation; explicitly eligible selective guards SHALL use their applicable write proof while preserving namespace lifecycle protection.

#### Scenario: A write invalidates namespace-guarded entries for the whole namespace

- **WHEN** a write advances the namespace generation
- **THEN** every cached entry using an ordinary namespace guard for that namespace is rejected at the next lookup, regardless of which document the write touched

#### Scenario: A write follows an ordinary unique-key result

- **WHEN** a positive or negative unique-key result uses an ordinary namespace guard and a write advances that namespace's generation
- **THEN** its next lookup rejects the result even when selectively guarded queries in the same namespace prove that write irrelevant

#### Scenario: Namespace creation invalidates and reclaims a pre-creation namespace-guarded entry

- **WHEN** a namespace-guarded entry (e.g. a negative unique-key lookup) is admitted while its collection does not yet exist, and the collection is then created
- **THEN** the namespace generation advanced by creation makes that entry ineligible for hits, and creation physically reclaims it via the namespace's entry index the same as a clear, rather than leaving it to age out

#### Scenario: A selective result proves a write irrelevant

- **WHEN** a processed write advances the ordinary namespace generation but an eligible selective guard proves the write irrelevant
- **THEN** that selectively guarded query result remains eligible without preserving any ordinary namespace-guarded entries or weakening document-identity invalidation

### Requirement: Compatible sources retain namespace and availability guards

Compatible lookup SHALL validate the actual resident source with the same applicable ordinary or selective guard and database-availability rules as exact lookup. Compatibility metadata SHALL NOT make stale, rolled-back, evicted, or otherwise ineligible sources reusable. Admission SHALL retain existing generation and availability capture checks.

#### Scenario: A write is processed before the narrower execution

- **WHEN** a larger result is cached and the manager processes a write that invalidates the source before consuming a new smaller-limit cursor
- **THEN** the older source is rejected and the new execution reads from MongoDB

#### Scenario: Stream continuity is lost and restored

- **WHEN** stream uncertainty invalidates the larger source before a subsequent smaller-limit execution
- **THEN** availability bypass or recovery guards prevent reuse of the pre-transition source

#### Scenario: Invalidation races candidate selection

- **WHEN** an applicable guard generation changes after a covering token is selected but before its validity decision
- **THEN** the candidate is rejected under the same lookup boundary as an exact entry

#### Scenario: An unrelated insert preserves a covering source

- **WHEN** a selective guard preserves a complete covering result through an unrelated insert
- **THEN** a matching smaller-limit request can reuse that source without adding a separately retained prefix
