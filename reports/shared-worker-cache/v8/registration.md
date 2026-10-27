# Shared worker cache: native admission queue

This registration addresses [issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272). Commit it before candidate timing. The [performance configuration](config.json) preserves version 5's workloads, calibration rule, paths, schedules, phases, repetitions, inference and thresholds. Its pending rates and durations must be filled only by fresh baseline-only calibration and committed before candidate timing. No version 5 measurement is reused as a version 8 comparison.

The single candidate remains `shared-index`. It combines version 7's local miss capture with `native_admission_queue`: the worker encodes the admission before returning and posts it to a bounded native queue in its existing session mapping. The owner drains batches through the same capture validation and authoritative core. A full queue falls back to the socket. The [design](../../../openspec/changes/archive/2026-10-17-reduce-shared-cache-miss-cost/design.md#native-admission-queue) defines ordering, limits and failure handling. This extends the selected shared-index family; it introduces no new hit mechanism or candidate-selection floor. Sorted finds retain their existing path.

[Version 7](../v7/results.md) did not meet the eight-worker miss P99 bound. Its complete evidence stays frozen and is not reused in version 8 inference. The new queue targets worker socket-send cost and owner wakeups; admission encoding and core insertion still run in Python.

All version 5 phases run fresh: screening, confirmation, capacity, active, cold and sensitivity. Version 5's stopping rules apply, but no skipped phase may support issue acceptance or promotion. Failed setup and capacity windows remain in the report. The cold phase must pass the existing P95 and P99 upper-confidence-bound delta criteria in both execution models at both required worker counts. A cold pass alone cannot establish promotion. Missing evidence is incomplete, never a pass.

The separate [fault configuration](fault-config.json) preserves version 6's complete scripted transition protocol, hot set, applicability, repetitions and limits, enabling the same candidate change. It runs all cases afresh; version 6's recorded results do not qualify the changed candidate. This configuration isolates fault transitions from steady-state performance as in version 6.

Exploratory before/after cold-window profiles identify owner CPU, requests and IPC work. They do not select offered rates, thresholds, sample counts or exclusions. Safety evidence must include untracked-identity writes, reset/restart, unavailable-available transitions, progress expiry followed by recovery, native-read errors, cancellation, token expiry and malformed tokens before decision timing. Queue tests additionally cover publication before reuse, wraparound, concurrent producers, full-queue fallback, malformed queue records and control-peer detachment. Startup samples drain queued admissions before checking residency; measured windows retain the existing schedule and latency definitions.

## Reproduce

Use the [contributor environment](../../../CONTRIBUTING.md). From the repository root:

```bash
source scripts/testcontainers-bridge.sh
uv run -- python -m benchmarks.stream_cost.shared_cache.run --calibrate-baselines --config reports/shared-worker-cache/v8/config.json --output benchmark-reports/shared-worker-cache/v8-calibration.json
uv run -- python -m benchmarks.stream_cost.shared_cache.run --config reports/shared-worker-cache/v8/config.json --freeze benchmark-reports/shared-worker-cache/v8-calibration.json
```

Commit the frozen configuration, then run each performance phase with `--phase <phase> --config reports/shared-worker-cache/v8/config.json --output benchmark-reports/shared-worker-cache/v8-<phase>.json`. Analyze it with `python -m benchmarks.stream_cost.shared_cache.analysis <report> --config reports/shared-worker-cache/v8/config.json --phase <phase> --blocks <registered blocks>`. The performance protocol and block counts are inherited from the [version 5 registration](../v5/registration.md).

For fault trials:

```bash
uv run -- python -m benchmarks.stream_cost.shared_cache.run --phase fault --config reports/shared-worker-cache/v8/fault-config.json --output benchmark-reports/shared-worker-cache/v8-fault.json
uv run -- python -m benchmarks.stream_cost.shared_cache.analysis benchmark-reports/shared-worker-cache/v8-fault.json --config reports/shared-worker-cache/v8/fault-config.json --phase fault
```

Use clean committed sources for measurements, a new output path per invocation and `--resume` only under the runner's existing matching-environment rule. Raw reports stay untracked. The results record must identify revision and configuration digests and distinguish complete registered evidence from exploratory or incomplete runs.
