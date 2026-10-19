# Worker fault recovery registration v1 (superseded)

V1 remains unchanged so attempted measurements retain their original
configuration digest. V1 was not frozen and no evidence matrix ran. V2 through
v4 are superseded; v8 is current. See [registration v2](../v2/registration.md),
[registration v3](../v3/registration.md), and
[registration v4](../v4/registration.md), and
[registration v5](../v5/registration.md),
[registration v6](../v6/registration.md).

The standalone all-case smoke repeat recovered six of seven applicable cells.
Independent worker restart missed the p99 recovery condition in a late bucket.
The calibration command stopped during a validation window after a write missed
the registered scheduling tolerance. Cleanup then raised a pipe error that
obscured the setup failure. Offline analysis of the complete calibration
validation windows also showed that V1's selected workload and recovery checks
could not pass the null-fault gate.

Keep V1's raw smoke and partial calibration outputs under the untracked
`benchmark-reports/worker-fault-recovery/` directory. The V2 configuration
records the corrected recovery rule and revised calibration selection.

The current registration is [registration v7](../v7/registration.md).

The current registration is [registration v8](../v8/registration.md).
