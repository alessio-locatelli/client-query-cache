## Purpose

Keep process-local cache entries usable only while a database change stream can
establish their event-driven coherency, and discard them on uncertainty.

## ADDED Requirements

### Requirement: Database-scoped coherency lifecycle
Each cache manager SHALL own one database-scoped change-stream lifecycle for
the collections it caches. The manager SHALL expose an explicit startup and
shutdown lifecycle and SHALL admit shared-cache reads only while its stream is
healthy.

#### Scenario: Successful startup
- **WHEN** the application starts a manager and the database change stream
  opens successfully
- **THEN** the manager becomes healthy and can admit eligible reads to cache

#### Scenario: Configuration failure at startup
- **WHEN** stream startup fails because the deployment or credentials do not
  permit change streams
- **THEN** startup reports the original failure and does not silently operate
  as a cache with disabled coherency

### Requirement: Event-driven invalidation
The manager SHALL process inserts, updates, replacements, deletes, drops,
renames, and invalidation events. A document event SHALL evict the affected
cached document identities. Any database change SHALL invalidate derived query
and aggregation results for that database.

#### Scenario: External document update
- **WHEN** another MongoDB client updates a cached document
- **THEN** the corresponding change event evicts the document and all of its
  cached identity aliases

#### Scenario: Membership-changing write
- **WHEN** a document change could alter a cached query's membership, ordering,
  projection, count, distinct values, or aggregation output
- **THEN** every derived result from that database becomes unavailable for
  cache hits

### Requirement: Race-safe result admission
The manager SHALL prevent an in-flight MongoDB read from writing a cache entry
after a relevant invalidation has been processed. A result that races with an
invalidation SHALL be discarded or retried before cache admission.

#### Scenario: Read overlaps an update
- **WHEN** MongoDB returns a read result while the manager processes a change
  that invalidates that result
- **THEN** the older result SHALL NOT remain admitted in the cache

### Requirement: Recoverable stream interruption
On a transient stream interruption, the manager SHALL mark itself recovering,
bypass shared-cache reads and admissions, and retry with bounded exponential
backoff and jitter. It SHALL resume from the latest usable resume token with
the same stream pipeline and options.

#### Scenario: Resumable disconnect
- **WHEN** a healthy stream disconnects and its resume token remains usable
- **THEN** the manager bypasses cache use until it resumes and then returns to
  healthy state without retaining entries admitted during the interruption

### Requirement: Clear on uncertain continuity
If the manager cannot prove stream continuity, including resume-token loss or
an invalidation event, it SHALL clear affected cache data before opening a new
stream. It SHALL not serve shared-cache entries until the replacement stream is
healthy.

#### Scenario: Resume history is unavailable
- **WHEN** MongoDB rejects resumption because the relevant oplog history is no
  longer available
- **THEN** the manager clears its cache, establishes a new stream, and bypasses
  shared-cache reads until that stream is healthy

#### Scenario: Collection drop or rename
- **WHEN** the manager receives an event that invalidates a watched collection
- **THEN** it clears entries associated with the affected namespace before
  continuing or re-establishing observation as required
