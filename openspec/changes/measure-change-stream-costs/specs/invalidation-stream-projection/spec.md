## Purpose

Minimize delivered event payload for cache invalidation without dropping the
event fields required for coherency, namespace handling, and stream resumption.

## ADDED Requirements

### Requirement: Minimal invalidation event shape
The database stream SHALL retain the unmodified event `_id` resume token,
`operationType`, `ns`, `documentKey`, `to`, `clusterTime`, and `wallTime` when
MongoDB supplies them. It SHALL exclude `fullDocument`,
`fullDocumentBeforeChange`, and `updateDescription` because the cache performs
invalidation rather than document synchronization.

#### Scenario: Large insert event
- **WHEN** MongoDB emits an insert event for a large document
- **THEN** the manager receives the retained invalidation fields and does not
  retain the inserted document as part of the stream event payload

#### Scenario: Rename event
- **WHEN** MongoDB emits a rename event
- **THEN** the manager receives both the source namespace and destination
  namespace needed to clear affected cache entries

### Requirement: Complete invalidation coverage
The stream configuration SHALL receive every insert, update, replace, delete,
drop, rename, and invalidate event needed by document and derived-result cache
semantics. It SHALL NOT discard inserts solely to reduce event traffic.

#### Scenario: Insert changes a cached result
- **WHEN** an insert can change the membership of a cached query or aggregation
- **THEN** the manager receives the event and invalidates derived results for
  the database

### Requirement: Resumability-preserving projection
The stream pipeline SHALL NOT modify or remove the event `_id`. Stream recovery
SHALL use the same projection and options that created a resume token.

#### Scenario: Recovery after projected event
- **WHEN** a stream resumes after processing projected invalidation events
- **THEN** it uses the retained token with the identical stream configuration
