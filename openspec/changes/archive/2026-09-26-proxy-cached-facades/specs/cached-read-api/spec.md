# Spec Delta

## MODIFIED Requirements

### Requirement: Sync and asyncio facades support the same cache contract

The library SHALL provide composed synchronous and native asyncio facades for supported collection reads. Neither facade SHALL close a caller-owned PyMongo client. Every `Collection`/`Database` method the facade does not itself override SHALL be directly callable on the facade, delegated to the wrapped PyMongo object with the caller's arguments unchanged, with no requirement to go through `.raw` first. Whenever a value obtained through this delegation — an attribute of the wrapped object, or the return value of calling a delegated method — is itself a PyMongo `Collection` or `Database`, the facade SHALL wrap it in a `CachedCollection`/`CachedDatabase` the same way `__getitem__` does, rather than returning the raw PyMongo object; every other delegated value SHALL be returned unwrapped. The wrapped PyMongo object SHALL remain reachable through `.raw`, and `.raw` SHALL be the only way to reach PyMongo's own semantics for `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, and `distinct` when the facade's cache-aware override of that method name cannot provide them (for example, a tailable or exhaust cursor, or a `$changeStream` aggregation pipeline).

#### Scenario: A caller closes a facade

- **WHEN** a caller closes a cached facade that wraps a caller-owned client
- **THEN** the facade releases its own resources without closing the caller-owned client

#### Scenario: A caller invokes a method the facade does not override

- **WHEN** a caller calls a `CachedCollection` or `CachedDatabase` method that the facade does not itself define (for example `insert_one`, `update_one`, `create_index`, or `create_collection`)
- **THEN** the facade delegates the call, with its arguments, unmodified to the wrapped PyMongo `Collection` or `Database` and returns its result, without the caller needing `.raw`

#### Scenario: A caller needs PyMongo's own semantics for an overridden method name

- **WHEN** a caller needs PyMongo's own behavior for `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, or `distinct` (for example a tailable or exhaust cursor, or a `$changeStream` pipeline) that the facade's cache-aware override of that name rejects or cannot provide
- **THEN** the caller reaches the wrapped PyMongo object through `.raw` and calls the method there, bypassing the facade's override entirely

#### Scenario: Attribute-style collection access stays cache-aware

- **WHEN** a caller accesses a collection by attribute on a `CachedDatabase` or a sub-collection by attribute on a `CachedCollection` (PyMongo's own dot-access idiom, for example `database.users` or `collection.chunks`), rather than by `[name]`
- **THEN** the facade returns a `CachedCollection` for it, the same as `database["users"]` or `collection["chunks"]` would, not the raw PyMongo `Collection` that attribute access would otherwise return

#### Scenario: A delegated method that returns a new Collection or Database stays cache-aware

- **WHEN** a caller calls a delegated method whose return value is itself a PyMongo `Collection` or `Database` (for example `database.get_collection(name)`, `database.with_options(...)`, or `collection.with_options(...)`)
- **THEN** the facade wraps that returned object in a `CachedCollection`/`CachedDatabase` before returning it, rather than handing back the raw PyMongo object
