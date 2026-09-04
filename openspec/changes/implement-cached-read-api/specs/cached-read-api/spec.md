## Purpose

This capability provides a narrow PyMongo-facing API for coherent process-local cached reads after the cache and change-stream foundations are healthy.

## ADDED Requirements

### Requirement: Sync and asyncio facades support the same cache contract
The library SHALL provide composed synchronous and native asyncio facades for supported collection reads. Neither facade SHALL close a caller-owned PyMongo client. Unsupported operations SHALL remain available through the raw collection.

#### Scenario: A caller closes a facade
- **WHEN** a caller closes a cached facade that wraps a caller-owned client
- **THEN** the facade releases its own resources without closing the caller-owned client

### Requirement: Only fully materialized supported reads are cached
The facades SHALL cache identity lookups and fully materialized bounded `find`, aggregation, count, estimated-count, and distinct results when the manager is healthy. They SHALL not admit partial, tailable, exhaust, oversize, session-bound, or otherwise unsupported reads.

#### Scenario: A caller abandons a cursor
- **WHEN** a caller partially consumes a cacheable-looking cursor
- **THEN** the facade does not admit its incomplete result to the cache

### Requirement: Cached reads retain database consistency boundaries
Cache-admitted reads SHALL use primary read preference and majority read concern. Session-bound reads and cache use during manager recovery SHALL bypass the cache. Returned values SHALL remain isolated from caller mutation.

#### Scenario: A session-bound read is requested
- **WHEN** a caller supplies a PyMongo session to a supported read
- **THEN** the facade delegates directly to PyMongo without a cache hit or admission
