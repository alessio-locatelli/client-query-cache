# Timed shared-cache fault results: version 6

All 75 repetitions passed their scenario safety checks and applicable timing criteria. The largest observed safe-readiness duration was 295 ms, within the registered five-second bound. The corrected run emitted no unhandled task exceptions.

Measured source: `a1b188e23255ac8a6ee1269681bea16fb2a4d0cc`. The configuration digest matches the frozen [registration](registration.md). The host was 13th Gen Intel(R) Core(TM) i3-13100, running Python 3.14.7, PyMongo 4.18.2 and `mongo:9.0.2`.

## Per-case observations

Each row shows the maximum of five repetitions, rounded up to milliseconds. N/A means the registration declares that interval inapplicable. Every row passed.

| Case                            | Detection (ms) | Safe readiness (ms) | First hit (ms) | Rewarming (ms) |
| ------------------------------- | -------------: | ------------------: | -------------: | -------------: |
| cancellation-during-publication |            N/A |                  24 |             24 |             61 |
| coordinator-pause               |           3069 |                  33 |             33 |             48 |
| coordinator-restart             |             20 |                 229 |            237 |            288 |
| history-loss                    |            N/A |                  24 |             33 |            126 |
| malformed-frames                |            N/A |                 N/A |            N/A |            N/A |
| owner-kill-during-local-hits    |             19 |                 268 |            277 |            332 |
| owner-pause-during-local-hits   |           3063 |                  33 |             33 |             52 |
| reattachment-after-restart      |             21 |                 257 |            264 |            300 |
| shutdown-during-startup         |              2 |                 295 |            295 |            354 |
| slow-reader                     |            N/A |                   4 |              4 |             12 |
| stream-interruption             |            N/A |                  18 |             18 |             29 |
| torn-read-stress                |            N/A |                 N/A |            N/A |            N/A |
| watch-pause                     |           2966 |                   9 |              9 |             31 |
| worker-killed-with-capture      |            N/A |                 222 |            222 |            226 |
| worker-replacement              |            N/A |                 224 |            224 |            231 |

## Interpretation and reproduction

These are observed transition upper bounds for the registered scripted hot set and mixed worker group. Polling, control round trips and scenario checks add observation delay. They do not measure recovery under version 5's offered load or supersede its failed miss-latency and capacity criteria.

A preliminary run at `aaabc16` met the timing and fencing criteria but exposed seven unhandled asyncio reader-task exceptions during owner shutdown. The reader fix in the measured revision handles the observed broken-pipe failure and has a deterministic regression. Both raw runs and their logs remain untracked; the table uses only the corrected run.

Use the [registered reproduction commands](registration.md#reproduce). Analysis reports every applicable duration and failure reason per repetition, including missing evidence, before computing the case-level outcomes. Raw reports and profiles are not committed.
