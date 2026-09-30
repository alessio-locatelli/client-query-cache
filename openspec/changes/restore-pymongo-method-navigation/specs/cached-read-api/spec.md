# Spec Delta

## ADDED Requirements

### Requirement: A cached read view accepts an existing PyMongo collection

The synchronous and asyncio managers SHALL provide a typed cached read view for a caller-supplied PyMongo collection belonging to that manager's client. The view SHALL retain that exact collection as `.raw`, including its configured options. A collection belonging to another client SHALL be rejected rather than silently watched through the wrong client.

#### Scenario: A caller uses one collection for writes and cached reads

- **WHEN** a caller obtains a PyMongo collection from the manager's client and requests its cached read view
- **THEN** direct calls on the PyMongo collection retain PyMongo's declared methods and return types, and the view's six supported read methods use that collection's options and the manager's cache

#### Scenario: A caller supplies another client's collection

- **WHEN** a caller requests a cached read view for a collection owned by a different client
- **THEN** the manager rejects the request before starting a change stream or performing a read

#### Scenario: A caller requests the same collection more than once

- **WHEN** a caller requests multiple cached read views for a collection from one cache manager
- **THEN** the views share that manager's cache entries and database change-stream supervisor, so a read through one view can hit an entry admitted through another
- **AND** callers are not promised that the views are the same Python object

### Requirement: Ordinary PyMongo operations retain native tooling

Cached database and collection views SHALL expose their own cache-aware reads and collection traversal, but SHALL NOT present arbitrary PyMongo methods as view methods. Ordinary PyMongo operations SHALL remain available on the caller-owned PyMongo object and through `.raw`, with PyMongo's own signatures and return types visible to static analysis and source navigation.

#### Scenario: A caller invokes a PyMongo write or administration method

- **WHEN** a caller needs `insert_one`, `drop`, `create_index`, `create_collection`, or another operation outside the cached view's declared surface
- **THEN** the caller can invoke it on the original PyMongo collection or database, or on the view's `.raw` object, and source navigation resolves to PyMongo's declared method
- **AND** the cached view does not expose that operation through an untyped delegation method

### Requirement: Sync and asyncio views expose cache-aware reads

Synchronous and asyncio facades SHALL support the same cache-aware read contract. Cached database and collection views SHALL expose indexed and attribute-style access to cache-aware collection views, without handing back an uncached PyMongo collection by accident.

#### Scenario: Attribute-style collection access stays cache-aware

- **WHEN** a caller accesses a collection by attribute on a `CachedDatabase` or a sub-collection by attribute on a `CachedCollection` (for example `database.users` or `collection.chunks`), rather than by `[name]`
- **THEN** the facade returns a `CachedCollection` for it, the same as `database["users"]` or `collection["chunks"]` would, not the raw PyMongo `Collection` that attribute access would otherwise return

#### Scenario: A caller changes collection options

- **WHEN** a caller obtains a PyMongo collection with `get_collection(...)` or `with_options(...)` and requests its cached read view
- **THEN** the view retains that optioned collection as `.raw` and applies its effective options to cache eligibility and direct reads

## MODIFIED Requirements

### Requirement: Raw access exposes overridden PyMongo methods

The `.raw` property SHALL expose the exact wrapped PyMongo object for calls requiring PyMongo semantics, including calls whose names are overridden by cache-aware reads.

#### Scenario: A caller needs PyMongo's own semantics for an overridden method name

- **WHEN** a caller needs PyMongo's own behavior for `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, or `distinct` (for example, a tailable or exhaust cursor, or a `$changeStream` pipeline) that the facade's cache-aware override of that method name cannot provide
- **THEN** the caller reaches the wrapped PyMongo object through `.raw` and calls the method there, bypassing the facade's override entirely

## REMOVED Requirements

### Requirement: Sync and asyncio facades expose cache-aware reads

**Reason**: The previous requirement promised that a method delegated through the cached view could return another cached view; the new boundary keeps PyMongo methods on the raw object and makes wrapping their result explicit.

**Migration**: Continue using cache manager indexing or attribute-style access for cached collection traversal. After calling `get_collection(...)` or `with_options(...)` on a PyMongo object, pass the returned collection to `cache_manager.cached(...)`.

### Requirement: Facades delegate methods they do not override

**Reason**: Generic delegation erases PyMongo method signatures and prevents source navigation on ordinary operations.

**Migration**: Call those operations on the original PyMongo collection or database, or on the cached view's `.raw` property. Use the cached view for its six declared read methods.
