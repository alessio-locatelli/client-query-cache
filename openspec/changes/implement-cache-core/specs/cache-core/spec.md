## Purpose

This capability provides bounded, process-local cache primitives that can safely store MongoDB-derived values before a public read API admits them.

## ADDED Requirements

### Requirement: Cache storage has a shared bounded budget
Each cache manager SHALL enforce one configurable weighted BSON memory budget shared by its collections. It SHALL evict least-recently-used entries as needed and SHALL reject entries larger than its maximum entry size.

#### Scenario: A new value exceeds the budget
- **WHEN** a cache admission would exceed the configured shared budget
- **THEN** the manager evicts eligible least-recently-used values or declines an oversized value without exceeding the budget

### Requirement: Cached values and aliases are isolated
The cache SHALL store BSON-derived values so caller mutation cannot change a future hit. It SHALL support document-identity aliases and namespace clearing so later coherency events can remove every affected entry.

#### Scenario: A caller mutates a cached document
- **WHEN** a caller changes a document returned from a cache hit
- **THEN** a later hit returns the originally cached value rather than the caller mutation

### Requirement: Namespace generations guard cache admission
Each cache namespace SHALL maintain a monotonically increasing generation. Each cached entry SHALL record the generation at which it was admitted. A database result that may be admitted SHALL capture the namespace generation before the database read and SHALL use one atomic admission operation to compare that captured generation with the current generation and insert the result only when they match. Invalidation's generation advancement SHALL be serialized with that admission operation, such as under the same lock or through an equivalent conditional operation. Cache lookup SHALL atomically reject an entry whose recorded generation does not match the current namespace generation, so generation advancement makes older entries ineligible for hits.

#### Scenario: Invalidation races an in-flight read
- **WHEN** a read captures generation 4 and an invalidation races the atomic compare-and-insert operation
- **THEN** either the admission completes first and the invalidation advances the generation afterward, or the invalidation completes first and admission rejects the result; a later cache hit cannot return a stale generation-4 value after invalidation

### Requirement: Cache health is inspectable
The manager SHALL expose immutable health, capacity, hit, miss, eviction, and bypass observations without returning document values, queries, credentials, or resume tokens.

#### Scenario: An application inspects the manager
- **WHEN** an application requests a cache inspection snapshot
- **THEN** it receives current lifecycle and capacity information without cached document contents
