# Shared-cache protocol fixtures

These frozen inputs exercise the benchmark protocol and its compatibility checks.
Version numbers identify recorded protocols, not supported library releases.
Their contents remain unchanged so recorded configuration digests still identify
the same workloads.

- `v2` through `v6` cover calibration, freezing, scheduling and fault handling.
- `v8` preserves the investigation protocol without a registered host constraint.
- `v9`, `v10`, `v12` and `v13` add environment, source-scope and proxy-policy checks.
- `v15` supplies the configuration and environment for the
  [retained identity study](../../../../reports/shared-worker-cache/v15/results.md).
- `runtime` contains the qualification and duration-validation schedules.

The runtime research driver requires an explicit `--config`. Use these inputs to
exercise a particular protocol; register the actual workload and environment for
a fresh engineering comparison. Historical reproduction uses the source revision
linked by each report and that revision's original paths.
