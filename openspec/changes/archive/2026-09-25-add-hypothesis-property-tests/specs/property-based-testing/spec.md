# Spec Delta

## Purpose

This capability defines which pure, invariant-bearing cache-core modules require Hypothesis-based property or stateful test coverage, and the rule contributors follow when choosing among Hypothesis, Faker, and fixed literal values.

## ADDED Requirements

### Requirement: Canonicalization and order-sensitive key invariants have property coverage

The repository SHALL verify, using Hypothesis-generated recursive BSON-like structures, that `canonicalize` is idempotent and that `canonicalize`/`order_sensitive_key`/`order_sensitive_discriminator_key` treat mapping key order and the bool/int distinction consistently, in addition to their existing fixed-example tests.

#### Scenario: A generated structure is canonicalized twice

- **WHEN** Hypothesis generates a recursive mapping/sequence/scalar structure and canonicalizes it twice
- **THEN** the second canonicalization produces a result equal to the first

#### Scenario: A generated mapping's keys are reordered

- **WHEN** Hypothesis generates a mapping and reorders its top-level keys
- **THEN** `canonicalize` of the reordered mapping equals `canonicalize` of the original, while `order_sensitive_key` differs whenever the reordering changed relative key order

### Requirement: Projection normalization invariant has property coverage

The repository SHALL verify, using Hypothesis-generated projection dictionaries, that `ensure_id_present_for_resolution` never produces a projection mixing inclusion and exclusion semantics.

#### Scenario: A generated projection is normalized

- **WHEN** Hypothesis generates a projection dictionary with arbitrary field names and inclusion/exclusion values, with or without an explicit `_id` entry
- **THEN** the normalized projection never mixes inclusion and exclusion semantics

### Requirement: Weighted LRU budget and ordering invariants have stateful coverage

The repository SHALL exercise `WeightedLru`'s put, touch, peek, and remove operations through a Hypothesis rule-based state machine asserting that resident-entry weight never exceeds the configured budget and that a strictly newer generation key is never displaced by a stale one.

#### Scenario: A generated operation sequence runs against the weighted LRU

- **WHEN** Hypothesis generates a sequence of put/touch/peek/remove operations over a bounded key and generation-key alphabet
- **THEN** the cache's used weight never exceeds its configured budget and no stale-generation entry ever displaces a newer one

### Requirement: Cache admission, lookup, write, and clear ordering has stateful coverage

The repository SHALL exercise `CacheCore`'s identity and namespace admission, lookup, write, and clear operations through a Hypothesis rule-based state machine asserting that a lookup never returns a value staler than the most recent successful write or clear affecting its key, and that admission bookkeeping accounts for exactly the resident entries.

#### Scenario: A generated operation sequence runs against the cache core

- **WHEN** Hypothesis generates a sequence of admission, lookup, write, and clear operations over a bounded identity/namespace alphabet
- **THEN** every lookup result reflects the most recent write or clear affecting its key, and admission bookkeeping accounts for exactly the resident entries

### Requirement: Unique-key field matching has property coverage

The repository SHALL verify unique-key discovery and filter matching using Hypothesis-generated field-name sets, filter shapes, and collations, in addition to the existing hand-enumerated cases.

#### Scenario: A generated filter is matched against a generated unique-key definition

- **WHEN** Hypothesis generates a unique-key field set and collation alongside a filter dictionary
- **THEN** the filter matches the unique key if and only if its field set and collation equal the unique key's, with only equality values present for every field

### Requirement: Test authors choose Hypothesis, Faker, or fixed values by a documented rule

The repository SHALL document, in its contributor guidelines, when to use Hypothesis property or stateful testing versus the `faker` fixture versus fixed literal values, so new tests apply the same tool consistently.

#### Scenario: A contributor adds a test for a new invariant-bearing algorithm

- **WHEN** a contributor writes a test asserting an invariant or exploring an operation-ordering space
- **THEN** the contributor guidelines direct them to Hypothesis rather than a hand-written loop over Faker-generated values or a single fixed example
