# Spec Delta

## MODIFIED Requirements

### Requirement: Sync and asyncio facades support the same cache contract

The library SHALL provide composed synchronous and native asyncio facades for supported collection reads. Neither facade SHALL close a caller-owned PyMongo client. Every `Collection`/`Database` method the facade does not itself override SHALL be directly callable on the facade, delegated unmodified to the wrapped PyMongo object, with no requirement to go through `.raw` first. The wrapped PyMongo object SHALL remain reachable through `.raw`, and `.raw` SHALL be the only way to reach PyMongo's own semantics for `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, and `distinct` when the facade's cache-aware override of that method name cannot provide them (for example, a tailable or exhaust cursor, or a `$changeStream` aggregation pipeline).

#### Scenario: A caller closes a facade

- **WHEN** a caller closes a cached facade that wraps a caller-owned client
- **THEN** the facade releases its own resources without closing the caller-owned client

#### Scenario: A caller invokes a method the facade does not override

- **WHEN** a caller calls a `CachedCollection` or `CachedDatabase` method that the facade does not itself define (for example `insert_one`, `update_one`, `create_index`, or `create_collection`)
- **THEN** the facade delegates the call, with its arguments, unmodified to the wrapped PyMongo `Collection` or `Database` and returns its result, without the caller needing `.raw`

#### Scenario: A caller needs PyMongo's own semantics for an overridden method name

- **WHEN** a caller needs PyMongo's own behavior for `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, or `distinct` (for example a tailable or exhaust cursor, or a `$changeStream` pipeline) that the facade's cache-aware override of that name rejects or cannot provide
- **THEN** the caller reaches the wrapped PyMongo object through `.raw` and calls the method there, bypassing the facade's override entirely
