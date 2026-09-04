## Why

Change-stream caching is workload-dependent. The library needs reproducible evidence about benefit and cost, but generic quality benchmarks and functional coherency must not be conflated with controlled stream-cost measurement.

## What Changes

- Add safe cache and stream measurement snapshots with explicitly limited meanings.
- Add controlled replica-set workloads, optional direct-path byte accounting, and versioned result reports.
- Add workload-selection guidance without automated adaptive cache disabling or hosted-runner performance gates.

## Capabilities

### New Capabilities

- `stream-cost-observability`: Safe logical cache and stream cost measurements.
- `stream-cost-benchmarking`: Controlled, reproducible change-stream cost benchmarks and reports.

### Modified Capabilities

- None.

## Impact

- Adds benchmark-only infrastructure and documentation after cached reads are functional.
