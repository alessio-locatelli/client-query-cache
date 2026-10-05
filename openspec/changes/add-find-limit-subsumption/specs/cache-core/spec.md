# Spec Delta

## MODIFIED Requirements

### Requirement: Namespace-guarded keys encode every output-affecting input

A namespace-guarded entry SHALL use a namespace-prefixed key encoding every output-affecting input. Distinct query identities SHALL have distinct physical keys. Reuse SHALL be allowed only by an explicitly specified semantic-equivalence or compatible-result contract; without such a contract, differing inputs SHALL NOT reuse a result.

#### Scenario: Different queries against the same namespace do not collide

- **WHEN** two `find` or `aggregate` reads against the same namespace differ in filter, pipeline, projection, sort, limit, skip, or collation
- **THEN** distinct query identities have separate physical keys and cannot supply one another's results except through explicitly supported compatible-result lookup; sharing a physical identity requires an explicitly supported equivalence

#### Scenario: Different `distinct` fields do not collide

- **WHEN** two `distinct` reads against the same namespace and filter differ only in the field whose values are distinguished
- **THEN** they are admitted and looked up as separate namespace-guarded entries, so neither can return the other's value list

## ADDED Requirements

### Requirement: Find limit compatibility preserves physical key separation

Different find limits SHALL remain distinct physical query identities. Limit subsumption SHALL use a separate compatibility relation and SHALL NOT remove the limit from the source's physical key.

#### Scenario: A covering source supplies a distinct limited shape

- **WHEN** a cached limit-100 source supplies an otherwise identical limit-10 request
- **THEN** the source retains its limit-100 physical key and the request is satisfied through compatibility rather than key equivalence

### Requirement: Find compatibility lookup has one cache outcome

An eligible find lookup SHALL check its exact key and supported covering entries before recording its outcome. A compatible hit SHALL record one hit, no miss, and normal LRU access for the resident source entry. Failure to find either an exact or compatible valid entry SHALL record one miss. Existing stream-unavailable bypass accounting SHALL be preserved.

#### Scenario: Exact lookup fails but compatibility succeeds

- **WHEN** a positive-limit lookup lacks a valid exact entry but finds a valid covering source
- **THEN** hits increase by one, misses remain unchanged, and subsequent budget pressure treats the source as recently used

#### Scenario: Every candidate is absent or invalid

- **WHEN** neither the exact key nor any covering candidate supplies a valid result
- **THEN** misses increase by one without an intermediate miss per candidate

#### Scenario: Database availability prevents lookup

- **WHEN** the source's database stream is unavailable
- **THEN** no compatible hit is recorded and the existing stream-unavailable bypass path is retained

### Requirement: Compatibility metadata follows resident source ownership

Compatibility lookup SHALL be confined to the requested namespace and query family, excluding only the limit from that family. Metadata SHALL reference admitted source entries without duplicating result payloads or creating entries for smaller limits. Replacement, eviction, rollback, namespace reclamation, and close SHALL remove obsolete references without deleting newer replacements. Metadata growth SHALL follow resident sources rather than historical queries.

#### Scenario: Unrelated cache contents grow

- **WHEN** unrelated namespaces and query families are added to the shared cache
- **THEN** a compatible find lookup examines only its own family rather than scanning the shared cache or whole namespace

#### Scenario: Many narrower cursors use one source

- **WHEN** many distinct smaller positive limits hit the same cached source
- **THEN** resident entry count and payload weight do not increase merely to represent those narrower queries

#### Scenario: Eviction precedes compatibility publication

- **WHEN** a source is evicted while admission publishes its compatibility metadata
- **THEN** the obsolete token is reclaimed and it cannot later supply a hit

#### Scenario: An obsolete token races replacement

- **WHEN** cleanup for an older source runs after a newer entry for that source key has been published
- **THEN** cleanup removes only the obsolete entry's references and leaves the newer source discoverable

#### Scenario: Namespace clear or manager close reclaims metadata

- **WHEN** a namespace is cleared or created, or the manager closes
- **THEN** its compatibility references are reclaimed along with the existing resident-entry lifecycle

### Requirement: Compatible sources retain namespace and availability guards

Compatible lookup SHALL validate the actual resident source with the same namespace-generation and database-availability rules as exact namespace lookup. Compatibility metadata SHALL NOT make stale, rolled-back, evicted, or otherwise ineligible sources reusable. Admission SHALL retain existing generation and availability capture checks.

#### Scenario: A write is processed before the narrower execution

- **WHEN** a larger result is cached and the manager processes a namespace write before consuming a new smaller-limit cursor
- **THEN** the older source is rejected and the new execution reads from MongoDB

#### Scenario: Stream continuity is lost and restored

- **WHEN** stream uncertainty invalidates the larger source before a subsequent smaller-limit execution
- **THEN** availability bypass or recovery guards prevent reuse of the pre-transition source

#### Scenario: Invalidation races candidate selection

- **WHEN** the namespace generation changes after a covering token is selected but before its validity decision
- **THEN** the candidate is rejected under the same lookup boundary as an exact entry
