## ADDED Requirements

### Requirement: `_id`-anchored single-document reads use identity guards

Synchronous and asyncio cached single-document reads whose mapping filter pins `_id` to one exact non-null, non-regex, non-operator value alongside additional predicates SHALL be guarded by that document identity when the effective collation is simple. The executed query and the cache key SHALL retain every additional predicate, and such an entry SHALL NOT be shared with a read whose predicates differ.

#### Scenario: Another document changes

- **WHEN** an `_id`-anchored result is cached and the manager processes an insert, update, replacement or deletion of a document with a different `_id`
- **THEN** the next identical read hits the cached result

#### Scenario: The anchored document changes

- **WHEN** an `_id`-anchored result is cached and the manager processes a write to the document with that `_id`, including one that makes it stop matching the additional predicates
- **THEN** the next read cannot return the pre-invalidation cached result

#### Scenario: A negative anchored result gains a match

- **WHEN** an `_id`-anchored read cached a missing result and the manager processes an insert or update of the document with that `_id` that makes it match
- **THEN** the next read fetches the current database result rather than the cached negative result

#### Scenario: Additional predicates distinguish entries

- **WHEN** a caller reads `{"_id": value}` and `{"_id": value, "owner": owner}` with otherwise equal options
- **THEN** each read uses its own entry, so neither can return the other's result

#### Scenario: The effective collation is not simple

- **WHEN** an `_id`-anchored read has a non-simple effective collation, whether explicit or inherited from the collection default
- **THEN** it uses generic namespace caching

#### Scenario: An anchored read spans writes

- **WHEN** the manager processes a write to the anchored document while the anchored read's database operation is in progress
- **THEN** the result is not admitted, whereas a write processed meanwhile to only other documents does not prevent admission

## MODIFIED Requirements

### Requirement: Generic single-document reads use namespace caching

Synchronous and asyncio cached single-document reads SHALL cache deterministic mapping filters that qualify for no exact-identity, `_id`-anchored, or unique-key optimization, including other compound predicates, regex-ID queries, and match-all reads. Their entries SHALL be guarded against writes anywhere in the queried collection and against namespace or stream-continuity changes. Negative results SHALL be cacheable under the same guard.

#### Scenario: A caller repeats a compound predicate

- **WHEN** a caller repeats an eligible single-document query whose predicates do not pin `_id` to one exact value, or pin it under a non-simple effective collation
- **THEN** the repeated query can hit a namespace-guarded entry without ignoring any predicate

#### Scenario: A caller repeats a regex-ID query

- **WHEN** a caller repeats an eligible single-document query whose `_id` predicate is a regular expression
- **THEN** the repeated query can hit a namespace-guarded entry rather than being treated as an exact-identity or unique-key read

#### Scenario: A matching document changes

- **WHEN** a generic result is cached and the manager processes a write affecting which document satisfies the query
- **THEN** the next read cannot return the pre-invalidation cached result

#### Scenario: A negative generic result gains a match

- **WHEN** a generic query cached a missing result and the manager processes an insert or update that creates a match
- **THEN** the next read fetches the current database result rather than the cached negative result

#### Scenario: A write touches another document

- **WHEN** a write to a different document in the same collection is processed after generic admission
- **THEN** the generic result is invalidated conservatively, while unrelated exact-identity and `_id`-anchored entries retain their narrower guards

#### Scenario: Index metadata is unavailable

- **WHEN** collection type and stream continuity are confirmed but unique-index discovery is inconclusive
- **THEN** an otherwise eligible deterministic mapping query can use the generic namespace path without assuming uniqueness
