# Verification: opt-in-telemetry

| Dimension    | Result                                                                                      |
| ------------ | ------------------------------------------------------------------------------------------- |
| Completeness | 14/14 tasks; all 15 added or modified requirements mapped                                   |
| Correctness  | All 31 scenarios traced to implementation and tests                                         |
| Coherence    | Construction-time policy, diagnostic boundaries and operational separation match the design |

## Evidence

| Contract group                  | Implementation                                                                                     | Regression coverage                                                                                                                                      |
| ------------------------------- | -------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Configuration and shared policy | `_core/manager.py`, `shared.py`, `_shared/coordinator.py`, `_shared/attachment.py`                 | `tests/core/test_telemetry.py`, `tests/shared_cache/test_diagnostics.py`, shared restart cases in `test_public.py`                                       |
| Disabled producer work          | Python/native cores, collection and cursor adapters, stream supervisors, owner and transport loops | Forbidden-constructor/clock/log hooks, default-mode retention and invalidation, queue overflow and recovery cases; full inventory in `producer-audit.md` |
| Diagnostic rejection            | Core and manager inspection, owner request boundary, `otel.py`                                     | Open/closed disabled-source matrices, fail-if-contacted endpoints, instrument-free registration                                                          |
| Safety and failures             | Operational generations, leases, progress publication, supervision and transport state             | Both-policy owner, attachment, startup and stream tests; native ring tests                                                                               |
| Enabled observation contracts   | Existing snapshot, stream-cost, health and metric producers behind the policy                      | Existing observation suites explicitly opt in, preserving immutable results, scopes, bounded reasons/windows and post-close contracts                    |
| PGO training                    | `scripts/pgo_training.py`                                                                          | Real workload passes plus traced scheduling for both mixes, shorter admission weighting, primitive scheduling and context restoration                    |

The full configured Python gate passed with 42,064 statements and 6,282 branches
covered, including its strict coverage-exclusion check. Native tests, concurrency
models, static checks, project lint and the strict documentation build also passed.
No CI or comprehensive performance-clearance claim is implied by these local checks.

The accepted benchmark-budget exception, build identities, measurements and
limitations are recorded in `reports/opt-in-telemetry/summary.md`. No additional
benchmark execution is required or planned for this change.

Spec synchronization preserves all eight modified requirements' prior obligations
and scenarios while adding their enabled-telemetry preconditions. Existing titles,
purposes and unrelated requirements remain unchanged. The seven added
requirements match their deltas; `telemetry-control` also retains its authored
purpose verbatim.

No critical issues, warnings or suggestions remain from verification.
