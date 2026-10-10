# Proposal

## Why

The steady-state evidence from `benchmark-concurrent-worker-workload` doesn't show how worker groups behave while a dependency fails. The [concurrency stress tests](../../../docs/development/concurrency-stress-tests.md) check that a single manager stays correct when its stream disconnects or loses its resume history, but they set no timing and don't cover several worker processes. The [shared-cache safety scenarios](../../../docs/development/research/shared-worker-cache-feasibility.md#safety-evidence) cover only the shared prototype, and their timed fault phase never ran. Without timed evidence for real failures, operators can't tell how long cached and direct workers take to recover, what bypasses they record meanwhile, or whether invalidation resumes afterwards.

## What Changes

- Add a disposable three-member replica set to the benchmark topologies, so that primary failover produces a real election.
- Run preregistered, timed fault trials against direct and independent worker groups under the registered steady-state workload. The trials cover connection loss, primary stepdown, unavailable resume history, and killing and replacing a worker. Cases, timing and the recovery criterion are in [design.md](design.md#fault-registration).
- Report fault outcomes for each case, separately from steady-state throughput and latency, and add them to the concurrent worker research report and the public recovery guidance.

This change depends on the harness generalization, the registration layout and the `multi-worker-benchmarking` capability that `benchmark-concurrent-worker-workload` introduces. That change must be archived first.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `multi-worker-benchmarking`: Adds requirements for timed fault trials and their reporting.

## Impact

- Code:
  - `benchmarks/stream_cost/topology.py` gains a three-member replica set.
  - `benchmarks/stream_cost/shared_cache/` gains a fault phase, worker-side injection controls and per-request timelines.
  - The shared prototype's history-loss injection moves into a module that the owner and the workers both use.
  - Tests are added under `tests/benchmark/stream_cost/`.
- Registration: new `reports/worker-fault-recovery/v1/`.
- Docs:
  - a fault section in `docs/development/research/concurrent-worker-workload.md`;
  - recovery figures in `docs/user/operations/deployment.md` or `docs/user/operations/monitoring.md`, where they refine existing guidance;
  - `context7.json` rules if that guidance changes.
- The library's public interfaces don't change.
