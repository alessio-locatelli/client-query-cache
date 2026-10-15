# Version 10: cold acceptance fails

The candidate at clean revision `1823ff90c720e4aae7e96610ed3d1441fa3d6c32` does not satisfy [issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272). All required cold P99 comparisons fail or are unstable. The [registered stopping rule](registration.md) ends this study before the remaining performance and fault phases; it supplies no acceptance evidence for those phases.

## Qualification

All thirty-eight baseline windows pass at the registered primary/cold/sensitivity rates of 1,006/1,000/319 requests/s. Acquisition and teardown take 2,070.63 seconds. Automated qualification verifies complete clean sources, configuration and producer digests, environment, native binary and all health/sample requirements, with no failures.

Manual source review identifies public 0.8.0 namespace reuse, reusable guards and call-local admission-state reuse as baseline changes relative to the historical v9 source. Fresh qualification covers those changes; it makes no claim of historical source compatibility. Environment freezing and qualification use the same local Fedora Toolbx and host Podman service on the registered i3-13100 host, without remote execution or host migration. Both required manual checks pass. No rate or duration adjustment is made.

## Cold results

All 144 windows complete healthily, with twelve balanced blocks per cell and no completion failures. The source revision and configuration match the qualification. Inference retains both bootstrap seeds, 200,000 draws, the registered confidence and all leave-one-out checks.

The limit is a **1 ms additive upper confidence bound** over direct reads:

| Model | Workers | P95 point / upper ms | P95  | P99 point / upper ms | P99      |
| ----- | ------: | -------------------: | ---- | -------------------: | -------- |
| async |       4 |        0.423 / 0.500 | pass |        1.493 / 2.035 | fail     |
| async |       8 |        0.524 / 0.578 | pass |        0.951 / 1.352 | unstable |
| sync  |       4 |        0.451 / 0.589 | pass |        1.156 / 2.241 | unstable |
| sync  |       8 |        0.513 / 0.602 | pass |        0.984 / 1.153 | fail     |

The analyzer returns `shared-index: defer`. Reduced isolated copying and guard costs do not establish acceptable cold tails. No hot, active, capacity, sensitivity or timed-fault result from an earlier candidate is substituted for this study.

## Reproduce

Use revision `1823ff9`, its frozen [configuration](config.json) and [environment](environment.json), and the commands in the [registration](registration.md). Run the baseline qualification and manual checks, then the complete cold phase with `--blocks 12` in analysis. Inspect the analyzer's verdict and failed comparisons: its process exit code alone does not establish acceptance. Raw qualification, cold and analysis outputs remain untracked under `/tmp/agents/issue-272-continuation/`.
