# Version 11: cold acceptance remains incomplete

The candidate at clean revision `970ff4b` does not satisfy [issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272). One required cold P99 comparison passes; the others fail or are unstable. The [registered stopping rule](registration.md) ends the study before the remaining phases.

## Qualification

All thirty-eight baseline windows pass at the registered primary/cold/sensitivity rates of 1,006/1,000/319 requests/s. Acquisition and teardown take 2,073.75 seconds. Automated qualification passes without failures. Manual source review confirms only the shared owner's admission polling interval changes relative to v10. Qualification uses the same registered physical host, local Toolbx and host Podman service. Both manual checks pass; rates and durations remain unchanged.

## Cold results

All 144 windows complete healthily, with twelve balanced blocks per cell and no completion failures. Inference retains both bootstrap seeds, 200,000 draws, the registered confidence and all leave-one-out checks. The limit is a 1 ms additive upper confidence bound over direct reads:

| Model | Workers | P95 point / upper ms | P95  | P99 point / upper ms | P99      |
| ----- | ------: | -------------------: | ---- | -------------------: | -------- |
| async |       4 |        0.461 / 0.502 | pass |        1.579 / 2.098 | fail     |
| async |       8 |        0.605 / 0.665 | pass |        0.946 / 1.091 | fail     |
| sync  |       4 |        0.366 / 0.392 | pass |        0.716 / 0.795 | pass     |
| sync  |       8 |        0.494 / 0.518 | pass |        0.843 / 0.982 | unstable |

The analyzer returns `shared-index: defer`. An upper bound below the limit does not override failed stability checks. No earlier hot, active, capacity, sensitivity or fault result substitutes for this candidate's evidence.

## Reproduce

Use revision `970ff4b`, its frozen [configuration](config.json), [environment](environment.json) and [registration commands](registration.md#reproduce). Inspect explicit analyzer verdicts, including stability. Raw outputs remain untracked under `/tmp/agents/issue-272-continuation/v11-*.json`.
