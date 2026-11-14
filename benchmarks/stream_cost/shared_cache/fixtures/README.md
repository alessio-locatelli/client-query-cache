# Shared-cache protocol fixtures

These inputs exercise calibration, scheduling, report validation and timed fault
recovery. `v4` covers the socket-owner comparison, `v5` adds shared-index paths,
and `v6` declares fault applicability and recovery timing. Version numbers name
protocols, not supported library releases.

For a fresh comparison, register the workload and environment explicitly; frozen
rates are host-specific. The [concurrent-worker protocol](../../../../reports/concurrent-worker-workload/v1/registration.md)
provides a sustained read/write workload. Historical studies link their immutable
inputs and source revisions from their reports.
