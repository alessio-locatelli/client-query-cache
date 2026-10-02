# Spec Delta

## ADDED Requirements

### Requirement: Metrics registration accepts manager inspection

The optional metrics bridge SHALL accept either execution model's manager as its statistics source, while preserving calls using the existing advanced cache-statistics object, including the existing keyword parameter name. Registration and collection SHALL remain local and read-only, and SHALL preserve existing instrument names, values, attributes, optional dependency behavior, and caller ownership of telemetry configuration.

#### Scenario: An application registers a manager

- **WHEN** an application supplies a synchronous or asyncio manager and its own meter
- **THEN** the bridge exposes the manager's existing cache and stream measurements without creating a telemetry provider or performing database I/O

#### Scenario: An advanced application keeps its existing registration

- **WHEN** an application supplies the existing advanced statistics source positionally or by the existing keyword name
- **THEN** registration continues to work with the same existing instrument identities

### Requirement: Bypass reasons have bounded metric cardinality

The bridge SHALL publish ordinary reason counts on a separate cumulative observable counter named `client_query_cache.cache.bypasses.by_reason` with the fixed attribute `cache.bypass.reason`. Each reason observation SHALL equal its snapshot count. The existing aggregate and oversized instruments SHALL retain their identities and semantics. The reason dimension SHALL use only the fixed public vocabulary and SHALL contain no database name, collection name, filter, document ID, credential, error message, or resume token.

#### Scenario: Expected and unhealthy bypasses are exported

- **WHEN** collection gathers ordinary reason counts for missing collections and unavailable streams
- **THEN** each has a distinct fixed reason observation on the new instrument and the aggregate remains separately available

#### Scenario: An oversized result is exported

- **WHEN** a result exceeds the maximum admission size
- **THEN** its count is available on the existing oversized instrument without appearing in the ordinary reason counter

#### Scenario: Many query shapes produce bypasses

- **WHEN** an application issues many distinct queries and collection names that bypass for the same reason
- **THEN** reason metric cardinality depends on the fixed vocabulary rather than on those queries or collection names
