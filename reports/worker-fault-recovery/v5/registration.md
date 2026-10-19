# Worker fault recovery registration v5 (superseded)

`config.json` is preserved unchanged because v5 was used in a timed smoke run.
Six cells recovered and passed correctness. The stepdown/direct cell recorded
`find:NotPrimaryNoSecondaryOk:13435`, which was not in the preregistered error
classes, so the runner retained it as a failed setup and exited unsuccessfully.
Calibration was not run under v5.

V6 adds this observed stepdown error class and preserves the workload,
calibration fraction and recovery criterion. See
[registration v7](../v7/registration.md) for the active configuration and
reproduction commands.

The complete v5 report is preserved at
`benchmark-reports/worker-fault-recovery/smoke-v5.json`.

The current registration is [registration v8](../v8/registration.md).
