## ADDED Requirements

### Requirement: The cached read view accessor names what it returns

The synchronous and asyncio managers SHALL provide `get_cached_collection(collection)` for requesting a cached read view of a caller-supplied PyMongo collection. The former `cached(collection)` name SHALL NOT remain available.

#### Scenario: A caller requests a cached view

- **WHEN** a caller passes a PyMongo collection from the manager's client to `get_cached_collection`
- **THEN** the manager returns the cached read view described by the existing view requirements

#### Scenario: A caller uses the former accessor name

- **WHEN** a caller invokes `cached(collection)` on a manager
- **THEN** the call raises `AttributeError`

### Requirement: Public manager members are documented or absent

Every public member of the synchronous and asyncio managers SHALL appear in the public guides or be absent from the public surface. Members that exist only to wire the manager to its cached views SHALL be private.

#### Scenario: A caller inspects the manager's public members

- **WHEN** a caller lists the public attributes of a manager
- **THEN** that list equals the documented set: `client`, `cache_core`, `get_cached_collection`, `snapshot`, `stream_health_snapshot`, `stream_cost_snapshot`, `active_stream_cost_databases`, and `close`
- **AND** an asyncio manager exposes the same names

#### Scenario: A caller looks for an eligibility probe

- **WHEN** a caller looks for `ensure_cache_eligible`, `cache_ineligibility_reason`, `default_collation_for`, or `unique_keys_for` on a manager
- **THEN** none is public, and cached reads still use them internally

### Requirement: Cached views expose only documented or PyMongo-mirroring members

`CachedDatabase` and `CachedCollection` SHALL expose as public members only the cached read methods and traversal that mirror PyMongo, plus `name`, `raw`, and their documented owner (`manager` or `database`).

#### Scenario: A caller inspects a cached view's public members

- **WHEN** a caller lists the public attributes of a cached database or collection
- **THEN** the list contains only those documented members, identically for synchronous and asyncio views
