# Proposal

## Why

The [failed guard run](https://github.com/alessio-locatelli/client-query-cache/actions/runs/37223173270/job/111497557677) rejected 59 of 60 base and all 60 proposed cache-hit blocks below its 5 ms floor. Fixed 256-hit batches are too short on that runner.

## What Changes

- Increase the bounded synchronous and asynchronous hit batches, verifying duration margin with fresh-process measurements.
- Retain matched base-owned workloads, cache-outcome assertions, 15 paired blocks, the 5 ms validity floor, and the 30% slowdown boundary.
- Keep measurement evidence in the commit body and raw output untracked.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. This calibrates an existing benchmark without changing its specified decision behavior; `skip_specs: true` applies.

## Impact

Only the cache-hit workload size in `benchmarks/stream_cost/guard_workload.py` changes. Library APIs, dependencies, other cases, and CI scheduling remain unchanged.
