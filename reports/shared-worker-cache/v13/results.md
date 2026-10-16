# Version 13: cold bounds pass; hot stability remains unmet

Candidate `80aa42749703b2ef6851d12b934748b760a09783` passes all required cold bounds, but the hot synchronous eight-worker request P99 comparison is unstable. It does not satisfy [issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272).

All thirty-eight fresh baseline windows qualify at the unchanged primary/cold/sensitivity rates of 1,006/1,000/319 requests/s. Qualification takes 1,871.59 seconds. Automated checks report no failures. Manual source review covers namespace contexts, scalar traversal, integer wire envelopes and the native relay on every path. The same local Toolbx and host Podman execution context establishes physical-host continuity; frozen environment and native binary checks match. Both manual checks pass. All seven release-mode Loom models pass before cold acquisition.

All 144 cold windows complete healthily, with twelve balanced blocks per cell, no completion failures, both bootstrap seeds, 200,000 draws and every leave-one-out check. The limit is a 1 ms additive upper confidence bound over direct reads:

| Model | Workers | P95 point / upper ms | P99 point / upper ms | Outcome |
| ----- | ------: | -------------------: | -------------------: | ------- |
| async |       4 |        0.339 / 0.373 |        0.591 / 0.694 | pass    |
| async |       8 |        0.519 / 0.554 |        0.729 / 0.888 | pass    |
| sync  |       4 |        0.337 / 0.357 |        0.532 / 0.610 | pass    |
| sync  |       8 |        0.428 / 0.453 |        0.676 / 0.834 | pass    |

Screening completes all 108 windows healthily and passes all thirty-six point comparisons. Confirmation completes all 144 windows healthily, without completion failures. Thirty-five comparisons pass. The hot sync eight-worker request P99 ratio over independent caches has a point estimate of 0.998 and upper bound of 1.240 against 1.25, but fails the registered stability checks. The analyzer returns `shared-index: defer`; the acceptable main upper bound does not override instability.

This candidate is abandoned after confirmation. Capacity, active, sensitivity and timed faults were not acquired; this is an incomplete study, not a registered successful stopping outcome. No historical or subsequent candidate phase substitutes for missing evidence. Version 14 registers a new implementation and an entirely fresh study.

Reproduce at revision `80aa427` with the [frozen registration](registration.md#reproduce), [configuration](config.json) and [environment](environment.json). Inspect explicit analyzer verdicts and stability. Raw reports remain untracked under `/tmp/agents/issue-272-continuation/v13-*.json`.
