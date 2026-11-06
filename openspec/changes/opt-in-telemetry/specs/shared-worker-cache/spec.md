## MODIFIED Requirements

### Requirement: Worker diagnostics are local and bounded

With telemetry enabled, a shared manager's `snapshot()` SHALL remain synchronous in both execution models, perform no I/O and report cumulative hits, misses, ordinary bypasses and oversized results for that manager only. It SHALL also report an ordinary bypass count for every member of a fixed public reason vocabulary, including zeros, whose sum equals the ordinary bypass count. Oversized results SHALL be excluded from both.

#### Scenario: A worker inspects its manager

- **GIVEN** telemetry is enabled
- **WHEN** an application calls `snapshot()` on a synchronous or asyncio shared manager
- **THEN** it receives an immutable result immediately, without any request to the owner

#### Scenario: Reasons agree with the aggregate

- **GIVEN** telemetry is enabled
- **WHEN** reads bypass for several reasons while other threads record further bypasses
- **THEN** each returned snapshot's reason counts sum to its ordinary bypass count

#### Scenario: A result exceeds the entry limit

- **GIVEN** telemetry is enabled
- **WHEN** a result is larger than `max_entry_bytes`
- **THEN** the oversized count increases while the ordinary count and every ordinary reason are unchanged

### Requirement: Owner diagnostics are requested explicitly

With telemetry enabled, each shared manager SHALL provide `owner_snapshot()`, synchronous for the synchronous manager and awaitable for the asyncio manager, as the only way to obtain owner-wide information. Each call SHALL issue at most one request to the owner, and none while the attachment is cooling down after a failure. Cache hits, misses, `snapshot()` and idle managers SHALL issue no diagnostic request.

#### Scenario: Diagnostics are requested

- **GIVEN** telemetry is enabled
- **WHEN** an application calls `owner_snapshot()` on either manager
- **THEN** one request reaches a reachable owner and an immutable result of the same shape is returned

#### Scenario: No diagnostics are requested

- **GIVEN** telemetry is enabled
- **WHEN** a manager serves hits and misses and its `snapshot()` is read repeatedly
- **THEN** the owner receives no diagnostic request

#### Scenario: A manager is closed

- **GIVEN** telemetry is enabled
- **WHEN** an application calls `owner_snapshot()` after closing the manager
- **THEN** it raises the closed-manager error rather than reporting an unavailable owner
