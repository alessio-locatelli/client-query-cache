# Version 12: eight-worker cold bounds remain unmet

The clean candidate `3d2ec251c5a75ea39c492268ed1dc6c063599546` passes both four-worker cold P99 comparisons but does not satisfy [issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272). At eight workers, async P99 is unstable and sync P99 fails. The [registered stopping rule](registration.md) ends the study before the remaining performance and fault phases.

## Qualification

All thirty-eight fresh baseline windows pass at the unchanged primary/cold/sensitivity rates of 1,006/1,000/319 requests/s. Acquisition and teardown take 1,880.59 seconds. Automated qualification reports no failures and verifies the frozen native binary and relay TCP policy. Manual source review records the scalar changes affecting independent caches and TCP_NODELAY on every relay path. Qualification runs on the same registered physical host through local Toolbx and host Podman. Both manual checks pass; no rates or durations change.

## Cold results

All 144 windows complete healthily, with twelve balanced blocks per cell and no completion failures. Inference retains both bootstrap seeds, 200,000 draws, the registered confidence and every leave-one-out check. The limit is a 1 ms additive upper confidence bound over direct reads:

| Model | Workers | P95 point / upper ms | P95  | P99 point / upper ms | P99      |
| ----- | ------: | -------------------: | ---- | -------------------: | -------- |
| async |       4 |        0.410 / 0.455 | pass |        0.749 / 0.875 | pass     |
| async |       8 |        0.597 / 0.644 | pass |        0.799 / 1.020 | unstable |
| sync  |       4 |        0.368 / 0.399 | pass |        0.762 / 0.873 | pass     |
| sync  |       8 |        0.481 / 0.502 | pass |        0.955 / 1.086 | fail     |

The analyzer returns `shared-index: defer`. The relay correction and scalar costs do not establish the required eight-worker bounds. No historical hot, active, capacity, sensitivity or timed-fault result substitutes for this candidate's evidence.

## Reproduce

Use revision `3d2ec25`, its frozen [configuration](config.json), [environment](environment.json) and [registration commands](registration.md#reproduce). Inspect explicit analyzer verdicts and stability, rather than process exit status alone. Raw qualification and cold reports remain untracked under `/tmp/agents/issue-272-continuation/v12-*.json`.
