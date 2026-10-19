# Worker fault recovery registration v7 (superseded)

`config.json` is preserved unchanged. Its seven-cell smoke passed all
injection, recovery, request-count and correctness checks. Calibration passed
the steady family at 689 requests/second, but two of six stepdown validation
windows exceeded the registered write-schedule tolerance at 2,232
requests/second. Calibration was inconclusive and v7 was not frozen.

V8 preserves the v7 workload and calibration fraction, and lowers only the
stepdown family cap to 1,000 requests/second. See
[registration v8](../v8/registration.md) for the active configuration and
reproduction commands.

The v7 smoke and calibration reports remain under
`benchmark-reports/worker-fault-recovery/`.
