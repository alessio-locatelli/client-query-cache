## Purpose

Control optional diagnostic collection without weakening cache correctness or concealing operational failures.

## ADDED Requirements

### Requirement: Telemetry requires construction-time opt-in

`CacheCoreConfig` and `SharedCacheConfig` SHALL expose `enable_telemetry=False`. Only exact built-in booleans SHALL be accepted, otherwise raising `CacheConfigurationError`. The setting SHALL remain fixed for each core or shared server lifetime. Both execution models and all storage implementations SHALL honor it.

#### Scenario: Default construction

- **WHEN** an application constructs a process-local core or shared server without enabling telemetry
- **THEN** optional diagnostic collection is disabled

#### Scenario: Explicit enablement

- **WHEN** an application supplies `enable_telemetry=True`
- **THEN** collection starts at construction and preserves the enabled observation contracts

#### Scenario: Invalid setting

- **WHEN** a caller supplies `1`, `None`, a string, or another non-boolean value
- **THEN** configuration construction raises `CacheConfigurationError` naming `enable_telemetry`

### Requirement: Disabled operations skip observation work

Disabled operation SHALL skip diagnostic counter updates, reason normalization, diagnostic locks and mutable collectors, lag sampling, observation-only clock reads, event re-encoding for byte metrics, diagnostic health bookkeeping, and routine diagnostic log preparation. This applies to reads, admission, eviction, invalidation, stream iteration, transport and owner loops. A mode check is permitted; a zero-latency guarantee is not implied.

#### Scenario: Reads and admission with telemetry disabled

- **WHEN** an application hits, misses, bypasses, exceeds result limits, declines retention, or evicts entries
- **THEN** no diagnostic recording calls, reason normalization, counter updates or telemetry-only allocations occur

#### Scenario: Background activity with telemetry disabled

- **WHEN** streams deliver events or an owner handles requests and connections
- **THEN** invalidation and transport proceed without measurement encoding, samples, command counts, peak counts or busy-time measurement

### Requirement: Diagnostic access rejects disabled collection

When telemetry is disabled, cache snapshots, stream-health snapshots, stream-cost snapshots, active stream-cost database discovery, stream-cost reset and owner snapshots SHALL raise `CacheConfigurationError` directing callers to `enable_telemetry=True`. Rejection SHALL occur locally before diagnostic I/O or report construction. Advanced inspection interfaces SHALL follow the same rule. Disabled inspection SHALL NOT fabricate zero values or silently enable collection.

#### Scenario: Disabled diagnostics are called

- **WHEN** an application invokes any listed diagnostic interface on a disabled source, including after close
- **THEN** it receives the actionable configuration error without a report, owner request or collection activation

#### Scenario: Enabled diagnostics after close

- **WHEN** an application inspects an enabled source after close
- **THEN** existing post-close result and error contracts remain applicable

### Requirement: Shared workers inherit the server policy

The shared server's telemetry setting SHALL propagate through its connection descriptor to every attachment and owner incarnation. Worker-local diagnostics and owner diagnostics SHALL use that setting without independent worker overrides. Restart and reattachment SHALL preserve the policy without adding diagnostic requests to ordinary reads.

#### Scenario: Workers attach to an enabled server

- **WHEN** synchronous and asyncio workers attach or reattach through its connection descriptor
- **THEN** worker and owner telemetry are enabled under the same policy

### Requirement: Cache safety and failure reporting remain active

Telemetry settings SHALL NOT alter cache eligibility, results, admission, invalidation, capacity enforcement, stream recovery, lease expiry, progress publication or shutdown. Required state and synchronization SHALL remain active. Persistent failures and actionable warnings SHALL remain visible even when telemetry is disabled.

#### Scenario: Upstream progress expires with telemetry disabled

- **WHEN** the shared owner's upstream progress stops beyond its safeguard interval
- **THEN** workers bypass stale cache state and recovery fences old entries as under enabled collection

#### Scenario: Stream startup fails with telemetry disabled

- **WHEN** a change stream cannot start because permissions are missing
- **THEN** the failure remains visibly reported and reads follow the ordinary fallback and retry policy

### Requirement: Observation contracts apply to enabled sources

Requirements for collected counts, samples and diagnostic reports in other capabilities SHALL apply only to telemetry-enabled sources. Vocabulary and public result types SHALL remain available regardless of collection policy. Required operational state SHALL follow its own contract in both modes.

#### Scenario: A disabled read bypasses

- **WHEN** eligibility rules require native execution
- **THEN** the read bypasses without collecting the otherwise specified bypass observation
