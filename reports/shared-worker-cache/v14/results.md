# Version 14: cold stability remains unmet

Candidate `ccf0eb7ac944203912dd6ba63179ff4524733e07` does not satisfy [issue #272](https://github.com/alessio-locatelli/client-query-cache/issues/272). All P95 comparisons pass, but three P99 comparisons fail or are unstable. The [registered cold stopping rule](registration.md) ends the study before later performance and fault phases.

All thirty-eight fresh baseline windows qualify at unchanged primary/cold/sensitivity rates of 1,006/1,000/319 requests/s, taking 1,893.10 seconds. Automated checks report no failures. Manual source review records the shared-only default integer classification change, with independent caches and relay behavior unchanged. The same local Toolbx and host Podman context establishes physical-host continuity; frozen environment and native binary checks match. Both manual checks pass.

All 144 cold windows complete healthily, without completion failures. Inference retains twelve balanced blocks per cell, both bootstrap seeds, 200,000 draws and every leave-one-out check. The limit is a 1 ms additive upper confidence bound over direct reads:

| Model | Workers | P95 point / upper ms | P95  | P99 point / upper ms | P99      |
| ----- | ------: | -------------------: | ---- | -------------------: | -------- |
| async |       4 |        0.348 / 0.449 | pass |        0.600 / 1.013 | unstable |
| async |       8 |        0.420 / 0.545 | pass |        0.535 / 0.922 | unstable |
| sync  |       4 |        0.287 / 0.417 | pass |        0.407 / 0.631 | pass     |
| sync  |       8 |        0.494 / 0.585 | pass |        1.027 / 1.275 | fail     |

The analyzer returns `shared-index: defer`. Classification savings do not establish stable cold-tail acceptance. Every sync window still opens four data sockets per worker and performs one selection RPC per thread before using native admissions. Version 15 investigates removing that unnecessary dependency on the data channel.

Reproduce at revision `ccf0eb7` with the [frozen configuration](config.json), [environment](environment.json) and [registration commands](registration.md#reproduce). Inspect explicit verdicts and stability. Raw reports remain untracked under `/tmp/agents/issue-272-continuation/v14-*.json`.
