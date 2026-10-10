# Proposal

## Why

Application workers duplicate resident cache values as well as MongoDB change streams. The completed [shared-invalidation study](../../../docs/development/research/shared-invalidation-feasibility.md) did not evaluate shared storage, leaving its memory benefit and access costs unresolved.

## What Changes

- Investigate one optional cache for a group of application processes on one host, following the full development workflow.
- Build a representative research prototype and compare it with independent managers and direct MongoDB reads under the preregistered protocol in [design.md](design.md#measurement-protocol).
- Use the [decision gate](design.md#decision-gate) to choose production integration or an evidence-backed deferral. The gate stopped the candidate at screening, so this change delivers the research tooling, its registration and the [research report](../../../docs/development/research/shared-worker-cache-feasibility.md) without a supported shared-cache mode.

## Capabilities

### New Capabilities

- `shared-cache-benchmarking`: Comparable resource, latency, scaling, and failure evidence for shared cached values.

### Modified Capabilities

None. The conditional `shared-worker-cache` capability and the `cache-core`, `change-stream-coherency` and `cached-read-api` deltas were removed after the gate deferred integration, as [Outcome handling](design.md#outcome-handling) requires.

## Impact

The research adds `benchmarks/stream_cost/shared_cache/`, its tests, the registrations under `reports/shared-worker-cache/`, a launch smoke under `research/shared_cache_launch/` and the development research report. `_core/manager.py` gains an encoded-entry seam that the research owner needs; standalone behaviour and public interfaces are unchanged. No user guide, example, README, Context7 rule or dependency changes.
