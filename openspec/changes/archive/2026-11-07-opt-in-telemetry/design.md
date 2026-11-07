# Design

## Context

See [proposal.md](proposal.md) for motivation and the [telemetry-control delta](specs/telemetry-control/spec.md) for the agreed policy. Public process-local managers use the Rust `LocalCacheCore`, the shared owner uses `SharedOwnerCore`, and the Python reference core remains relevant to tests and advanced use.

### Audited collection sites

| Location                                                        | Unconditional observation work                                                                                                                                                                                | Operational work that must survive                                                                               |
| --------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `_core/snapshots.py`, `_core/manager.py`                        | Statistics lock, counters, bypass maps and retention records; pending decline bookkeeping through admission retries                                                                                           | Admission decisions, generation guards, retention limits, LRU occupancy and eviction                             |
| `native/shared-index/src/local_cache.rs`, `_core/native.py`     | Hit/miss/bypass/oversized/eviction/decline updates; explicit recording methods acquire the state mutex; setup allocates a Python stream registry; stream recording crosses into Python                        | State mutexes needed for cache operations, value/alias residency, key sizing needed to enforce configured limits |
| `_shared/adapters.py`                                           | `LocalObservation`, hit/miss increments, bypass enum lookup and dictionary update, oversized counts                                                                                                           | Outcome selection, MongoDB fallback and attachment recovery                                                      |
| `_shared/attachment.py:EndpointCounters`                        | Sync/async connection, request, timeout, failure, byte, one-way and native-admission counters, including `_one_way_frame` and receive helpers                                                                 | Frame encoding/validation, request IDs, deadlines and `AdmissionRecovery` generation/fallback state              |
| `native/shared-index/src/ring.rs`, ring bindings in `python.rs` | Atomic `R_DROPPED` increment when a touch ring is full; its only production read is owner diagnostics                                                                                                         | Head/tail publication, capacity checks, touch delivery and admission-queue ordering                              |
| Both `streams.py` modules                                       | Poll recording and per-event `dict(event)` plus BSON encoding solely to count logical bytes                                                                                                                   | Stream iteration, resume tokens, retries and availability transitions                                            |
| `_core/stream_events.py`, `_core/stream_cost.py`                | Wall and monotonic clock reads, timestamp conversion, lag arithmetic, registry locks, sample deques and apply-reading objects; projected `wallTime` and `clusterTime` have no routing consumer in this module | Routing fields, stream resume identity, invalidation and namespace metadata updates                              |
| `_core/stream_health.py`, stream coordinators                   | Separate diagnostic registry, registry locks and bound status callbacks on startup/failure                                                                                                                    | Supervisor health, retry state and locks used to control cache availability                                      |
| `_shared/coordinator.py:UpstreamProgress`                       | Command-name formatting and count dictionaries under a lock; aggregate-pipeline inspection for stream-open counts; `_fresh_since` tracking                                                                    | `observed` progress, lease freshness, fencing and shared-index progress publication                              |
| `_shared/coordinator.py:OwnerCounters`, owner loop              | Request/byte/outcome/security-event counts, peak calculations, end-of-loop clock read for busy time, startup clock for uptime                                                                                 | Queue sizes and limits, captures, lease timestamps, selector/sweep deadlines and access checks                   |
| `_core/manager.py` logging                                      | Eviction logging and deferred `partial` completion callbacks, namespace log dictionaries and routine close logging                                                                                            | Reclamation and admission completion itself; actionable failure reporting throughout the package                 |
| `otel.py`, diagnostic snapshot methods                          | Repeated full snapshots per instrument, repeated lag sorting per percentile; explicit owner diagnostics traverse and serialize state via IPC                                                                  | No ongoing collection work is needed here until the caller requests it                                           |

Snapshot allocation, export, IPC and percentile calculations are already demand-driven. They remain costs of opting in. Optimizing enabled OpenTelemetry callbacks is outside this change; it is unnecessary to establish the disabled-path contract and requires no separate follow-up commitment.

The native `ByteRelay` byte counters are part of explicitly constructed benchmark instrumentation, not the cache manager's ordinary execution path. Constructing that relay already opts into measurement; its counters remain intrinsic to that measurement tool.

## Goals / Non-Goals

Acceptance follows the disabled-path contract in the telemetry-control delta. Enabled OpenTelemetry collection retains its existing cost model.

### Validation constraints

The user authorized limited benchmarking and excluded multi-hour runs. During implementation, compare affected paths against a recorded `main` revision using matched release builds, dependencies, workloads and host conditions. Limit cumulative benchmark execution, including benchmark warmup, to five minutes; build and environment preparation are separate. Use bounded comparison runs and stop at that budget rather than launching full benchmark suites. The validation test tier, including tests marked `benchmark`, has a separate allowance from this comparison budget. The user accepted the original comparison's recorded cleanup overrun as an exception; `reports/opt-in-telemetry/summary.md` contains the corrected accounting. No further execution is authorized under that original allowance.

Reuse the existing `benchmarks/public_shared_cache.py` runner and its sample, repetition, model, path and workload selectors. Start with a small identity-read workload covering hot and cold reads on independent and shared paths in both execution models; counterbalance baseline and candidate order across repeated pairs. Measure latency, throughput and process CPU for the candidate's default mode, and include enabled-mode controls where the budget permits. Keep result/cache-use verification outside timed loops and do not enable telemetry just to satisfy the runner's existing snapshot checks. Reduce samples or repetitions if needed, stating the resulting uncertainty. Record any unmeasured paths or inconclusive differences rather than claiming comprehensive regression clearance; do not accept a reproducible slowdown without investigation under the repository policy.

The release profile also needs training on disabled branches. The user authorized a separate five-minute comparison of PGO builds trained with 80% disabled / 20% enabled and 50% disabled / 50% enabled workload time; builds and training are preparation outside that execution budget. Preserve each workload's total timed training allocation and the existing shorter allocation for limited-admission workloads. Keep enabled verification passes, exercise both policies in training tests, and select the final mix from matched measurements against `main`. Record uncertainty and rejected runs with the results.

Structural inspection and focused functional checks establish which work executes; timing alone cannot prove absence of collection. The final producer-audit deliverable is specified in task 4.3. Performance results belong in `reports/opt-in-telemetry/summary.md` with commands, revision IDs, workload settings and limitations; keep raw output untracked as required by `AGENTS.md`.

## Decisions

### Carry policy through existing configuration

Append the flag to the two public configuration dataclasses, preserve positional field order and validate it separately from numeric fields. Pass it through `OwnerConfig`, `AttachmentConfig`, the connection descriptor, native setup and constructor bindings. Obtain it from the core or attachment at the existing manager seams rather than adding manager keyword options. Expose a read-only `enable_telemetry` property on supported statistics sources and update the statistics protocols, native stubs and metrics test doubles accordingly. This allows registration preflight without taking a snapshot.

Independent worker switches would permit cheap workers with a measured owner, but create combinations and configuration mistakes. Implicit activation at first inspection would avoid a setting but cannot reconstruct earlier counts and would silently change later costs. Neither alternative needs a prototype or further research; the policy is settled in the telemetry-control delta.

### Guard producers before preparing observations

Check the immutable policy before record calls, reason normalization, clock reads, serialization and temporary diagnostic objects. Do not install no-op collectors and continue calling them on every hit. Allocate mutable collectors only in enabled mode; keep a lightweight immutable mode indicator. Native code must gate updates within its cache operations, not just its Python-facing wrappers. Explicit advanced record methods may return immediately when disabled; they must not activate collection or acquire telemetry-only locks.

Keep eligibility reasons where they determine fallback; skip conversion performed solely for counting. Retention decisions and retry deduplication required for correctness remain active, but telemetry-only pending-decline lists and count assembly do not. Avoid duplicating complete cache algorithms by mode. A branch is preferable to a parallel implementation whose correctness could drift; its cost is subject to the validation constraints above.

### Separate supervision from measurement

Keep the command listener registered: it provides the shared cache's progress safety signal. Its count paths and diagnostic `_fresh_since` history become conditional. Preserve `observed`, required locking and publication. Reuse an operational timestamp where one already exists; do not remove owner-loop time values used for sweep or capture expiry. Gate only extra timing and accounting.

Skip both call sites and collectors for stream telemetry, including internal reset calls on reopen. A disabled public reset must reject as specified; normal recovery must never invoke that rejected path. Select the event projection once at stream construction: omit telemetry-only `wallTime` and unused `clusterTime` in disabled mode while retaining every routing/resume field. Enabled projections retain measurement inputs. Do not add full-document lookup. Retain supervisor health used by availability, but create and update the separate inspection registry only in enabled mode.

Removing the listener entirely looks cheaper but breaks progress expiry and stale-read protection. Keeping all health and progress bookkeeping would be simpler but leaves observation-only work enabled. The code establishes this distinction; no research or separate task is necessary to choose between these alternatives.

Carry the shared policy into native session-ring creation and attachment. Cache it on each ring object and gate only the dropped-touch increment; retain the existing shared-memory header layout and all queue atomics. A layout change would increase compatibility work without removing more collection work. No prototype or further research is necessary. In attachment recovery, never put `recovery.enqueued(...)` or other state transitions inside a telemetry condition merely because their boolean result currently controls a counter increment.

### Apply errors at diagnostic boundaries

Implement the diagnostic-error and registration contracts in their respective deltas at the existing public boundaries. Use the policy property from the configuration decision for OpenTelemetry preflight, so registration does not need a throwaway snapshot.

Returning zero-valued snapshots would preserve result shapes but falsely imply measured inactivity. Returning partial reports would require optional-field changes throughout reports and consumers. Both were presented to the user through the policy choice; rejection was selected. No additional investigation is required.

## Risks / Trade-offs

- Enabling telemetry globally in test fixtures could conceal regressions in ordinary use. Keep default-mode verification independent of diagnostic snapshots.
- Configuration inconsistency across processes could produce incomplete reports. Existing trusted descriptors provide the propagation seam described above.
- Health and timing names mix operational and diagnostic responsibilities. The audit table identifies the distinction; tasks pair producer changes with recovery and lifecycle verification.
- Suppressing all logging would conceal failures. The telemetry-control safety requirement applies even where routine log preparation is gated.
- Existing OpenSpec requirements often assume collection. Their applicability is governed by the telemetry-control scope requirement rather than repeated policy definitions in each capability.

## Migration Plan

Consumer and public-guidance migration is assigned in tasks 1.1, 1.2 and section 4. The ordinary OpenSpec completion sequence applies after implementation.
