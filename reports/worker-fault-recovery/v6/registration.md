# Worker fault recovery registration v6 (superseded)

`config.json` is preserved unchanged. Its seven-cell smoke passed every
injection, recovery, request-count and correctness check. Baseline calibration
is preserved at `benchmark-reports/worker-fault-recovery/calibration-v6.json`.
The steady family validated at 1,431 requests/second. The stepdown family
selected 4,362 requests/second, but four of six validation windows exceeded
the registered write-schedule tolerance. Calibration was inconclusive, no
complete null-fault result was produced, and v6 was not frozen.

V7 preserves the workload, error classes and recovery criterion while
lowering the calibration selection fraction to 0.125. See
[registration v7](../v7/registration.md) for the active configuration and
reproduction commands.

The current registration is [registration v8](../v8/registration.md).
