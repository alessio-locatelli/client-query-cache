# Spec Delta

## ADDED Requirements

### Requirement: Order-sensitive key nodes carry no redundant layers

A canonical cache key SHALL represent each order-sensitive mapping, sequence, and numeric-subtype value, and the sorted representation of a scalar find filter, as one tagged node whose payload is canonicalized in place, without an enclosing generic-sequence layer. An order-sensitive mapping SHALL keep its field names and values in one payload tuple, without a tuple per field.

#### Scenario: A one-predicate filter forms its key

- **WHEN** a generic `find_one` filter `{"code": "C0000001"}` forms its namespace-guarded key
- **THEN** the filter's part of the key consists of two tuples: the tagged mapping node and its payload `("code", "C0000001")`

#### Scenario: Nested order-sensitive values form a key

- **WHEN** a filter contains an embedded document, an array, a double, and a 64-bit integer
- **THEN** each of these values appears in the key as one tagged node, and no generic-sequence node directly contains a private key tag

#### Scenario: A scalar find filter forms its family

- **WHEN** a `find()` filter qualifies for sorted scalar predicates
- **THEN** its family holds the sorted filter as one tagged node around the ordered mapping node, without a generic-sequence layer between them

### Requirement: Compact key nodes keep key equality

The compact representation SHALL NOT change which inputs share a canonical key or a find family. Bool and integer values, numeric subtypes in discriminators, mapping field order in order-sensitive inputs, and mappings versus sequences SHALL stay distinct. Equal keys SHALL hash equally. Unhashable values and NaN SHALL remain uncanonicalizable, so their reads bypass the cache.

#### Scenario: Distinguished inputs keep separate keys

- **WHEN** two otherwise identical discriminators differ only in `True` versus `1`, `1` versus `1.0` or `Int64(1)`, the field order of an embedded filter document, or a mapping versus an equivalent pair sequence
- **THEN** their canonical keys are unequal

#### Scenario: Numerically equal identities share a key

- **WHEN** identities `1`, `1.0`, `Int64(1)`, and `Decimal128("1")` are canonicalized as identities, alone or embedded in a document
- **THEN** they produce equal keys with equal hashes

#### Scenario: Non-reflexive values are rejected

- **WHEN** a discriminator contains a double NaN inside an order-sensitive node, or an identity is a decimal NaN
- **THEN** canonicalization fails as uncanonicalizable and the read bypasses the cache

### Requirement: Re-canonicalization reuses canonical subtrees

Canonicalizing an already canonical key SHALL return that key object. A structure that embeds canonical subtrees, such as a find or generic `find_one` discriminator built around a canonical family, filter, or read shape, SHALL reference those subtrees without rebuilding them.

#### Scenario: A discriminator wraps a canonical family

- **WHEN** a find discriminator is built from a canonical family and a limit
- **THEN** the discriminator references the same family object, and canonicalizing the discriminator again returns the same discriminator object

#### Scenario: A family arrives in raw and canonical form

- **WHEN** one find family is canonicalized from its raw read shape and another copy is decoded from its canonical wire form
- **THEN** both produce equal keys with equal family hashes, so exact lookup and limit-compatible lookup reach the same resident entries
