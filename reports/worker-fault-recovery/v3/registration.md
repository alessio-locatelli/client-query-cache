# Worker fault recovery registration v3 (superseded)

`config.json` is preserved unchanged because v3 was used in a timed smoke run.
Five of seven cells recovered and passed correctness. Connection-loss/direct
and worker-restart/independent had one later request-P99 bucket above the
registered threshold, after several earlier buckets had passed. V3 therefore
reported both trials as unrecovered and skipped their correctness probes.

The smoke exposed that the detector revoked recovery because of any later
failing bucket, although the requirement defines recovery as the first bucket
that meets the registered criterion. V4 records the first passing bucket and
retains later bucket results in the timeline. See
[registration v5](../v5/registration.md) and
[registration v6](../v6/registration.md) for the current configuration and
reproduction commands.

The complete v3 report is preserved at
`benchmark-reports/worker-fault-recovery/smoke-v3.json`.

The current registration is [registration v7](../v7/registration.md).

The current registration is [registration v8](../v8/registration.md).
