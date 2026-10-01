# Spec Delta

## ADDED Requirements

### Requirement: Explicit barriers prove applied invalidations

A manager SHALL provide an opt-in database-scoped barrier for a validated causal write boundary. Successful return SHALL prove that every relevant invalidation through that boundary has been applied to that manager before subsequent cache hits or admissions can use pre-invalidation state. Receiving an event, storing a resume position, observing a healthy stream, or seeing one event at the boundary's timestamp SHALL NOT alone establish success. The guarantee SHALL cover single-document and query-result invalidation and SHALL NOT cover writes beyond the supplied boundary, other managers, or future independent writers.

#### Scenario: A write changes a cached document and a query result

- **WHEN** a caller supplies a valid completed-write boundary affecting a cached identity and a cached collection query
- **THEN** successful barrier return means both affected pre-write cache entries have been invalidated in that manager

#### Scenario: Several events share the boundary timestamp

- **WHEN** several relevant events share a timestamp and only some have been applied
- **THEN** the barrier does not report success based on the first applied event at that timestamp

#### Scenario: A transaction changes multiple collections

- **WHEN** a supported committed transaction establishes a valid boundary and changes multiple collections in the named database
- **THEN** successful barrier return covers all relevant invalidations in that database through the committed boundary

#### Scenario: A read spans invalidation

- **WHEN** a read captured pre-invalidation state and finishes after the barrier's relevant invalidations have been applied
- **THEN** its old generation cannot be admitted as a valid cache entry after successful barrier return

#### Scenario: A later writer remains independent

- **WHEN** an independent write occurs beyond a successfully completed barrier's boundary
- **THEN** ordinary cached reads retain their documented eventual behavior for that later write

### Requirement: Barrier inputs have verifiable provenance

A barrier SHALL validate its database/deployment scope and completed-write provenance before accepting a boundary. It SHALL reject unacknowledged writes, uncommitted transaction boundaries, missing operation information, foreign deployment scope, and any input whose relationship to applied stream progress cannot be established. It SHALL NOT infer a specific write boundary solely from wall time, an unrelated observed cluster time, or a consumer-library method's successful return.

#### Scenario: A write has an explicit supported boundary

- **WHEN** an acknowledged completed write provides a supported verifiable boundary for the manager's deployment
- **THEN** the barrier can use that immutable boundary without concurrently sharing the application's live session with its worker

#### Scenario: An upstream consumer hides its boundary

- **WHEN** a library completes a raw write but supplies no information establishing a supported causal boundary
- **THEN** the manager does not claim to recognize that specific write automatically, and public guidance states the unsupported boundary acquisition case

#### Scenario: A transaction is still open

- **WHEN** an input describes operations in an uncommitted transaction
- **THEN** the barrier rejects it rather than reporting the operations invalidated

### Requirement: Barrier lifecycle is bounded and explicit

Every barrier call SHALL have an explicit finite positive timeout and one monotonic deadline covering activation, progress acquisition, waiting, and recovery. Timeout, unsupported startup, closed management, or loss of the required continuity SHALL produce an explicit unsuccessful outcome rather than success inferred from local clearing. Cancellation SHALL release call-specific resources without stopping a shared healthy stream. Pending waits SHALL be released unsuccessfully during manager shutdown. Synchronous and asyncio barriers SHALL provide equivalent guarantees and failure semantics.

#### Scenario: A quiet database reaches a supported boundary

- **WHEN** a supported write or no-op boundary has been passed with no later relevant event
- **THEN** the barrier can establish completion using its proven progress mechanism without requiring an unrelated application write

#### Scenario: The deadline expires during startup

- **WHEN** stream activation or boundary acquisition consumes the call's deadline
- **THEN** the call terminates unsuccessfully within its documented timeout/cleanup bounds rather than starting another full waiting interval

#### Scenario: Resume history is lost

- **WHEN** the stream loses continuity needed to prove a pending boundary
- **THEN** the pending call fails explicitly rather than treating cache clearing and a new healthy stream as proof that the old boundary was applied

#### Scenario: A waiter is cancelled

- **WHEN** one asyncio barrier waiter is cancelled while other waits share the stream
- **THEN** its retained waiter state is released and the other waits and shared stream remain operational

#### Scenario: Shutdown races a pending wait

- **WHEN** the manager closes before a pending barrier establishes completion
- **THEN** the wait is released with an explicit closed outcome and no recovery can reopen a stream for it

### Requirement: Barriers do not synchronize ordinary reads

Ordinary cached reads SHALL retain the existing eventual coherency contract without an implicit per-read causal wait. Barrier state SHALL retain progress per watched database and outstanding calls, not an unbounded history of application writes. Barriers SHALL NOT automatically write marker data or decode opaque resume tokens to manufacture a proof.

#### Scenario: An application does not request a barrier

- **WHEN** an application performs ordinary cached reads without the opt-in operation
- **THEN** those reads do not issue barrier requests or wait for a causal boundary

#### Scenario: A long-lived application completes many barriers

- **WHEN** an application repeatedly completes or cancels barrier calls
- **THEN** completed-call and per-write history does not accumulate in manager memory
