## ADDED Requirements

### Requirement: Unique keys are discovered from server index metadata, not declared

The facades SHALL discover unique keys for a namespace from `list_indexes()` rather than from a caller declaration. A discovered key SHALL be limited to indexes with `unique: true` that have no `partialFilterExpression`, are not `sparse`, and are not a hashed key, since only such an index unconditionally guarantees uniqueness for every document. A read SHALL only take the alias path through a discovered key when the read's effective collation exactly matches the index's collation. Discovery SHALL be re-performed whenever the namespace epoch has advanced since the last check, using the same re-verification trigger as view detection, and SHALL be shared across every facade handle for the same namespace.

#### Scenario: A unique index is discovered and used

- **WHEN** a caller reads by an equality filter matching a unique, non-partial, non-sparse, non-hashed index's field set under the read's effective collation
- **THEN** the facade treats the read as a unique-key read eligible for alias-based identity caching

#### Scenario: A partial, sparse, or hashed unique index is not used

- **WHEN** a unique index has a `partialFilterExpression`, is `sparse`, or is hashed
- **THEN** the facade does not use it as a unique key, and a matching read is treated as a generic bounded read instead

#### Scenario: A read's collation does not match the index's collation

- **WHEN** a caller's read specifies a collation different from a unique index's collation (or specifies none while the index has a non-default collation)
- **THEN** the facade does not use that index as a unique key for the read, and the read is treated as a generic bounded read instead

#### Scenario: An index is added or removed without a namespace epoch advance

- **WHEN** a unique index is created or dropped on a live collection without the collection being dropped and recreated
- **THEN** the facade does not detect the change until the namespace's epoch next advances for an unrelated reason, or a new `CacheManager` is constructed

### Requirement: Unresolved and negative unique-key reads are guarded conservatively

A unique-key read whose alias has not yet been resolved to a document identity SHALL capture only the namespace generation before the database read, since the document identity is unknown until the read responds, and SHALL admit a namespace-guarded entry keyed by the unique-key definition, value, and read shape. On a match, the facade SHALL resolve and record the alias for that key value; if the caller's own projection excludes `_id`, the facade SHALL still fetch `_id` from the server for resolution — by overriding `_id: 0` to `_id: 1` for an inclusion-style caller projection, or by omitting the caller's `_id: 0` for an exclusion-style one, never by adding `_id: 1` to an exclusion-style projection, which MongoDB rejects as a mixed inclusion/exclusion projection — and SHALL NOT expose `_id` in the returned or cached value. On a match, the facade SHALL also admit an identity-guarded entry for the same document and read shape, guarded by the document's current identity generation and the namespace epoch, in addition to the namespace-guarded entry; this is required because cache-core prunes an alias once no cached entry references the identity it resolves to, and a namespace-guarded entry carries no such reference, so an alias published without an accompanying identity-guarded entry would be pruned immediately and never actually route a later read to the identity-guarded path. On no match, the facade SHALL admit a negative result guarded by the captured namespace generation, not by a document identity generation. A subsequent read of a key value with a resolved alias SHALL capture that document's identity generation and the namespace epoch before the read and SHALL admit an identity-guarded entry keyed by that identity and the read's shape, not by the namespace generation.

#### Scenario: A unique-key value is looked up for the first time

- **WHEN** a caller reads by a unique key with no existing alias for that key value
- **THEN** the facade captures the namespace generation before the read, and admits the resulting match or negative result guarded by that namespace generation rather than an identity generation, keyed by the unique-key definition, value, and read shape

#### Scenario: A first-time match also admits an identity-guarded entry

- **WHEN** a caller reads by a unique key with no existing alias, and the read matches a document
- **THEN** the facade admits both the namespace-guarded entry for the unique-key value and an identity-guarded entry for the matched document, so the newly published alias has an identity-guarded entry keeping it alive and a subsequent read of the same key value takes the identity-guarded path immediately

#### Scenario: A resolved unique-key alias is read again

- **WHEN** a caller reads by a unique key whose alias was already resolved by an earlier read
- **THEN** the facade captures that document's identity generation and the namespace epoch before the read and admits an identity-guarded entry keyed by that identity and the read's shape

#### Scenario: A unique-key match excludes `_id` from its projection

- **WHEN** a caller reads by an unresolved unique key with a projection that excludes `_id`, and the read matches a document
- **THEN** the facade resolves and records the alias using the document's `_id` fetched from the server, and neither the value returned to the caller nor the value admitted to the cache includes `_id`

#### Scenario: A unique-key match uses an exclusion-style projection

- **WHEN** a caller reads by an unresolved unique key with an exclusion-style projection that excludes `_id` alongside another field (e.g. `{"_id": 0, "secret": 0}`)
- **THEN** the facade omits the caller's `_id: 0` from the server-side projection rather than adding `_id: 1`, since `_id` is included by default once its exclusion is omitted and adding `_id: 1` would make the projection invalid

### Requirement: A resolved unique-key read re-verifies against its original predicate on a cache miss

A read of a key value with a resolved alias SHALL first attempt a cache lookup keyed by the resolved identity and the read's shape. On a cache miss, the facade SHALL query the database by the caller's original unique-key predicate (field and value), and SHALL NOT query by the resolved identity alone, because a write to the resolved document could have changed the field the alias was resolved from, or, after the namespace was dropped and recreated, the same identity value could now belong to an unrelated document. The facade SHALL compare the identity of the response (or its absence) against the identity the alias recorded. When they agree, the facade SHALL capture the document's current identity generation and admit or refresh the identity-guarded entry. When they disagree — a different document matched, or none did — the facade SHALL treat the alias as stale, discard or re-resolve it, and admit the result the same way an unresolved unique-key read would.

#### Scenario: A resolved alias is still accurate

- **WHEN** a cache miss occurs for a key value with a resolved alias, and a database query by the original predicate matches the same document identity the alias recorded
- **THEN** the facade admits or refreshes the identity-guarded entry for that document, confirming the alias remains valid

#### Scenario: A resolved alias has gone stale

- **WHEN** a cache miss occurs for a key value with a resolved alias, and a database query by the original predicate matches a different document identity than the alias recorded, or matches no document at all
- **THEN** the facade does not return or cache a value based on the stale alias's identity; it discards or re-resolves the alias and admits the result according to the query's actual outcome
