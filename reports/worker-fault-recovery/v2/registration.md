# Worker fault recovery registration v2 (superseded)

`config.json` is preserved unchanged because v2 was used in a timed smoke run.
That run is not evidence for recovery: every cell failed before injection
because the 150 requests/second smoke load left fewer than 16 keys available
for the post-recovery correctness probe. The smoke command also returned zero
for those unhealthy cells; the runner now treats any incomplete or failed
smoke cell as an unsuccessful command.

V3 lowered only the smoke rate to 100 requests/second. Its completed smoke
record exposed a recovery-detector issue. V4 and V5 record subsequent
calibration and smoke outcomes; v8 is current. See
[registration v3](../v3/registration.md),
[registration v4](../v4/registration.md),
[registration v5](../v5/registration.md), and
[registration v6](../v6/registration.md). V2 remains available to reproduce
its recorded attempt.

The failed report is preserved at
`benchmark-reports/worker-fault-recovery/smoke-v2.json`.

The current registration is [registration v7](../v7/registration.md).

The current registration is [registration v8](../v8/registration.md).
