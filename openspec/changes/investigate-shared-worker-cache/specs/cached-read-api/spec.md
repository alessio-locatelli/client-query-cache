# Spec Delta

These production additions apply only if the shared-cache investigation promotes an implementation.

## ADDED Requirements

### Requirement: Existing managers accept optional shared attachment

Both manager execution models SHALL support explicit shared-group attachment while retaining their existing standalone construction. Cached views SHALL retain their caller-owned native client and collection identity. Closing an attachment SHALL NOT close that client.

#### Scenario: A shared worker wraps an optioned collection

- **WHEN** an attached manager receives its own client's collection through `get_cached_collection`
- **THEN** the view retains that exact collection as `.raw`, including native options and the existing rejection of another client's collection

### Requirement: Shared reads preserve native read and cursor contracts

Attached managers SHALL apply the existing eligibility, read-profile, alias, query-shape, mutation-isolation and complete-result admission rules to all six supported read methods. Find and aggregation cursors SHALL retain native call shapes, consumption, snapshot, batching and cleanup contracts in both execution models.

#### Scenario: A shared worker repeats each supported read

- **WHEN** eligible `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count` or `distinct` calls are repeated across workers
- **THEN** shared hits return the documented result types and values while preserving each method's existing execution and eligibility rules

#### Scenario: A shared find cursor is partly consumed

- **WHEN** the worker closes a miss cursor before consuming its complete result
- **THEN** the partial result is not admitted to group storage and its admission ownership is released

#### Scenario: A shared hit cursor is already consuming its snapshot

- **WHEN** another worker's write is invalidated or the owner becomes unavailable
- **THEN** that started cursor finishes its isolated snapshot while a new execution rechecks authoritative state

#### Scenario: A session-bound query matches a shared entry

- **WHEN** a worker requests that query with an explicit or bound session
- **THEN** native session execution and validation occur without shared lookup or admission

### Requirement: Shared deployment guidance describes measured operation

Public guidance and Context7 rules SHALL describe the implemented attachment API, process ownership, security scope, budget accounting, recovery, shutdown and measured operating limits consistently. Shared mode SHALL NOT be documented as supported before production integration passes its decision gate.

#### Scenario: Measurements reject integration

- **WHEN** the shared-value investigation ends in deferral
- **THEN** user guides continue to describe standalone behavior and the development research report explains the evidence

#### Scenario: A deployment opts into shared caching

- **WHEN** a user follows the supported multi-worker example
- **THEN** it creates clients and attachments within workers, owns one coordinator explicitly, and explains rollback and its measured worker envelope
