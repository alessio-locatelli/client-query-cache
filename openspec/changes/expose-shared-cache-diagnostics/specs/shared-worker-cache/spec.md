# Spec Delta

## ADDED Requirements

### Requirement: Worker diagnostics are local and bounded

A shared manager's `snapshot()` SHALL remain synchronous in both execution models, perform no I/O and report cumulative hits, misses, ordinary bypasses and oversized results for that manager only. It SHALL also report an ordinary bypass count for every member of a fixed public reason vocabulary, including zeros, whose sum equals the ordinary bypass count. Oversized results SHALL be excluded from both.

#### Scenario: A worker inspects its manager

- **WHEN** an application calls `snapshot()` on a synchronous or asyncio shared manager
- **THEN** it receives an immutable result immediately, without any request to the owner

#### Scenario: Reasons agree with the aggregate

- **WHEN** reads bypass for several reasons while other threads record further bypasses
- **THEN** each returned snapshot's reason counts sum to its ordinary bypass count

#### Scenario: A result exceeds the entry limit

- **WHEN** a result is larger than `max_entry_bytes`
- **THEN** the oversized count increases while the ordinary count and every ordinary reason are unchanged

### Requirement: Bypass reasons separate eligibility from owner and capacity causes

The reason vocabulary SHALL distinguish request ineligibility, collection ineligibility, shared-scope restrictions, a database absent from the server configuration, stream states, namespace capacity, owner unavailability and metadata refresh. Reasons SHALL contain no database, collection, query, tenant or error text. An unrecognized reason SHALL count as unspecified.

#### Scenario: Reads bypass for different causes

- **WHEN** a read uses a session, a read targets a database the server does not list, a read supplies a locale collation, and a read occurs while the owner is unreachable
- **THEN** each is counted under its own distinct reason

#### Scenario: The owner supplies an unknown reason

- **WHEN** the owner reports a bypass reason outside the vocabulary
- **THEN** the manager counts it as unspecified without growing its reason storage

### Requirement: Owner diagnostics are requested explicitly

Each shared manager SHALL provide `owner_snapshot()`, synchronous for the synchronous manager and awaitable for the asyncio manager, as the only way to obtain owner-wide information. Each call SHALL issue at most one request to the owner, and none while the attachment is cooling down after a failure. Cache hits, misses, `snapshot()` and idle managers SHALL issue no diagnostic request.

#### Scenario: Diagnostics are requested

- **WHEN** an application calls `owner_snapshot()` on either manager
- **THEN** one request reaches a reachable owner and an immutable result of the same shape is returned

#### Scenario: No diagnostics are requested

- **WHEN** a manager serves hits and misses and its `snapshot()` is read repeatedly
- **THEN** the owner receives no diagnostic request

#### Scenario: A manager is closed

- **WHEN** an application calls `owner_snapshot()` after closing the manager
- **THEN** it raises the closed-manager error rather than reporting an unavailable owner

### Requirement: An unavailable owner is never reported as an empty cache

When the owner does not answer within the attachment's request deadline, `owner_snapshot()` SHALL return `None`. A returned snapshot SHALL carry an opaque owner incarnation and the owner's uptime, so that a replaced owner, whose counters restart at zero and whose cache is empty, is distinguishable from a healthy empty one.

#### Scenario: The owner is stopped

- **WHEN** the owner process is not running
- **THEN** `owner_snapshot()` returns `None` and does not raise

#### Scenario: The owner is restarted

- **WHEN** the server restarts the owner and the manager asks again after it recovers
- **THEN** the snapshot's incarnation differs from the earlier one, its uptime is shorter than the time since the earlier snapshot, and its cumulative counters restart from zero

### Requirement: Owner snapshots report capacity use

An owner snapshot SHALL report in-use and limit for the cache byte budget, index entries, tracked namespaces and attachment connections, and cumulative evictions and rejected attachment connections since the owner started. Values SHALL be bounded by configuration and SHALL contain no cached value.

#### Scenario: The cache byte budget is exceeded

- **WHEN** admitted results exceed the budget and older entries are evicted
- **THEN** the snapshot shows byte use at or below its limit and a nonzero eviction count

#### Scenario: Namespace capacity is exhausted

- **WHEN** reads target more collections than `namespaces` allows
- **THEN** the snapshot's namespace use equals its limit and the reading worker's `namespace_capacity` count increases

#### Scenario: Connection capacity is exhausted

- **WHEN** the owner refuses an attachment because its connection limit is reached
- **THEN** the rejected-connection count increases while the connection use does not exceed its limit

### Requirement: Owner snapshots report stream status without implying freshness

An owner snapshot SHALL list each configured database once, in configuration order, with exactly one of `not_started`, `starting`, `startup_failed`, `unavailable`, `progress_expired` or `healthy`. Each non-healthy status SHALL correspond to the condition that makes reads of that database bypass. `healthy` SHALL NOT be documented as a promise that a writer's latest change was processed.

#### Scenario: No read has touched a database

- **WHEN** an owner has served no read for a configured database
- **THEN** that database reports `not_started`

#### Scenario: A stream cannot start

- **WHEN** the owner cannot open a database's change stream
- **THEN** that database reports `startup_failed` while worker reads count `stream_starting`

#### Scenario: Progress stops

- **WHEN** an available stream makes no upstream progress beyond the safeguard interval
- **THEN** that database reports `progress_expired` and worker reads count `progress_expired`

### Requirement: Diagnostics expose no secrets or unbounded labels

Neither diagnostic SHALL expose the attachment capability, endpoint path, MongoDB URI or options, cached values, queries, collection names, tenant values or error text. The server-configured database names MAY appear.

#### Scenario: An application logs a diagnostic

- **WHEN** an application renders either diagnostic result
- **THEN** the text contains no credential, endpoint, query or collection identifier

### Requirement: Diagnostic types are public

The diagnostic result and enumeration types SHALL be importable from the package root, the synchronous package and the asyncio package, and SHALL be immutable.

#### Scenario: An application annotates diagnostics

- **WHEN** an application imports the diagnostic types from any of those packages
- **THEN** the import succeeds and `typing.get_type_hints` resolves every public field annotation
