## Purpose

Provide a safe, process-local memory backend with predictable resource use and
fresh caller values for document and derived-result caching.

## ADDED Requirements

### Requirement: Shared bounded cache budget
The in-memory backend SHALL apply one weighted least-recently-used budget across
the document and derived-result entries owned by a cache manager. Its default
maximum retained value size SHALL be 64 MiB, and it SHALL reject entries larger
than the default 1 MiB maximum entry size. Applications SHALL be able to set
both limits when constructing the backend.

#### Scenario: Budget exhaustion
- **WHEN** admitting a new cache entry would exceed the configured budget
- **THEN** the backend evicts least-recently-used entries until the entry fits
  or declines admission when the entry exceeds its entry limit

#### Scenario: Multiple collections share a manager
- **WHEN** cached collections use the same cache manager
- **THEN** their document and result entries compete within one configured
  memory budget rather than each receiving an unbounded private cache

### Requirement: BSON value storage
The in-memory backend SHALL retain BSON-encoded values and SHALL decode a new
value for each cache hit. Cache accounting SHALL include stored values and
cache metadata needed to retrieve them.

#### Scenario: Returned-value mutation
- **WHEN** a caller mutates a returned cached document or result list
- **THEN** the retained entry remains unchanged and later hits decode the
  original stored value

### Requirement: Explicit cache clearing
The backend SHALL support clearing all entries and clearing all entries for an
affected namespace. Clearing SHALL remove document aliases and derived results
associated with its scope.

#### Scenario: Coherency reset
- **WHEN** the coherency manager declares stream continuity uncertain
- **THEN** the backend removes entries in the specified scope before cache use
  resumes
