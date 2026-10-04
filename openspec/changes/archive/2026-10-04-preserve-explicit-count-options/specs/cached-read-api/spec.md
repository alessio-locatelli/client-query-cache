## ADDED Requirements

### Requirement: Count reads preserve explicit options

Synchronous and asyncio cached `count_documents` reads SHALL preserve explicitly supplied options in native execution. Cache keys SHALL distinguish options with different native behavior, including invalid bounds and `hint=None`, while omitted skip and integer `skip=0` SHALL share a cache shape. Omitted bounds SHALL count all matching documents. Native PyMongo/MongoDB errors SHALL propagate on cold and bypassed reads without reusing incompatible warm entries. General live-error policy is unchanged.

#### Scenario: Bounds are omitted

- **WHEN** a caller repeats an eligible count without `skip` or `limit`
- **THEN** all matching documents are counted and the result can be cached

#### Scenario: An explicit invalid option is supplied

- **WHEN** a caller supplies `limit=0`, `limit=None`, `skip=None`, or `hint=None` on a cold count or after warming an omitted-option count
- **THEN** the native error is preserved instead of returning the omitted-option count

#### Scenario: A count bypasses caching

- **WHEN** a caller supplies an explicit invalid option on a count that bypasses caching
- **THEN** native execution receives that value and preserves its error

#### Scenario: Zero skip is equivalent to omission

- **WHEN** a caller warms an eligible count with omitted skip and repeats it with `skip=0`, or performs these calls in reverse order
- **THEN** the repeated read reuses the same cached entry
- **AND** an explicit zero skip reaches native execution unchanged when that request performs the cold read
