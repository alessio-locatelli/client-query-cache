# Worker fault recovery registration v4 (superseded)

`config.json` is preserved unchanged. Its seven-cell smoke passed injection,
recovery, request-count and correctness checks. The calibration runs are
preserved at `benchmark-reports/worker-fault-recovery/calibration-v4.json` and
`calibration-v4-retry.json`. The complete retry report selected 2,849
requests/second but was inconclusive: two validation windows exceeded the
registered write-schedule tolerance. V4 was not frozen, and no evidence matrix
ran.

V5 keeps the v4 smoke rate and first-passing-bucket recovery rule, and lowers
the calibration selection fraction to 0.25. See
[registration v5](../v5/registration.md) and
[registration v6](../v6/registration.md) for the current configuration and
reproduction commands.

The current registration is [registration v7](../v7/registration.md).

The current registration is [registration v8](../v8/registration.md).
