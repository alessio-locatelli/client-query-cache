# Timed shared-cache fault results: version 6

All 75 repetitions passed their scenario safety checks and applicable timing criteria. The largest observed safe-readiness duration was below 213 ms, within the registered five-second bound; full rewarming was below 217 ms. The run emitted no unhandled task exceptions.

Measured source: `ab53e506e1056c7d3b36d776b3ff01492734fa57`, from a clean checkout. The configuration digest matches the frozen [registration](registration.md). The host was 13th Gen Intel(R) Core(TM) i3-13100, running Python 3.14.7, PyMongo 4.18.2 and `mongo:9.0.2`.

## Per-case observations

Each row shows the maximum of five repetitions, rounded up to milliseconds. N/A means the registration declares that interval inapplicable. Every row passed.

| Case                            | Detection (ms) | Safe readiness (ms) | First hit (ms) | Rewarming (ms) |
| ------------------------------- | -------------: | ------------------: | -------------: | -------------: |
| cancellation-during-publication |            N/A |                   8 |              8 |             39 |
| coordinator-pause               |           3332 |                  23 |             23 |             29 |
| coordinator-restart             |            108 |                 153 |            156 |            209 |
| history-loss                    |            N/A |                  18 |             19 |             86 |
| malformed-frames                |            N/A |                 N/A |            N/A |            N/A |
| owner-kill-during-local-hits    |            103 |                 144 |            147 |            198 |
| owner-pause-during-local-hits   |           3391 |                  14 |             14 |             19 |
| reattachment-after-restart      |            100 |                 171 |            171 |            195 |
| shutdown-during-startup         |             27 |                 146 |            148 |            189 |
| slow-reader                     |            N/A |                   1 |              1 |              7 |
| stream-interruption             |            N/A |                  15 |             15 |             28 |
| torn-read-stress                |            N/A |                 N/A |            N/A |            N/A |
| watch-pause                     |           3112 |                   2 |              2 |              7 |
| worker-killed-with-capture      |            N/A |                 211 |            211 |            215 |
| worker-replacement              |            N/A |                 213 |            213 |            217 |

## Interpretation and reproduction

These are observed transition upper bounds for the registered scripted hot set and mixed worker group. Full-set native reads, RPC timeouts, polling and control round trips add observation delay. This run also profiles the controller, which adds instrumentation overhead; spawned workers are not profiled. It does not measure recovery under version 5's offered load or supersede its failed miss-latency and capacity criteria.

The run at `a1b188e23255ac8a6ee1269681bea16fb2a4d0cc` is withdrawn as complete fault evidence: [PR #276](https://github.com/alessio-locatelli/client-query-cache/pull/276) identified incomplete fencing detection and duplicate idle-worker scenarios. The table uses only the corrected full-set and concurrent-read procedures in the registration.

The corrected coordinator-pause trials retain 12 terminal snapshots each, with 2,920–2,924 bytes of serialized probe content (`json.dumps`), compared with 640–700 snapshots and 165,377–180,875 bytes in the withdrawn run. Owner-pause trials additionally retain the start and stop traffic counters: 20 snapshots and 3,911–3,913 bytes each. Readiness probes avoid exhaustive residency scans. These counts describe reporting overhead, not cache throughput.

Use the [registered reproduction commands](registration.md#reproduce). For this run, the runner invocation used `python -m cProfile -o <profile> -m benchmarks.stream_cost.shared_cache.run` with the registered arguments. Analysis reports every applicable duration and failure reason per repetition. Raw reports, logs and profiles remain untracked.
