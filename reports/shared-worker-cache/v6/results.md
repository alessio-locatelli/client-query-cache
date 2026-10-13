# Timed shared-cache fault results: version 6

All 75 repetitions passed their scenario safety checks and applicable timing criteria. The maximum observed safe-readiness duration rounded up to 209 ms, within the registered five-second bound; full rewarming rounded up to 219 ms. The run emitted no unhandled task exceptions.

Measured source: `4db8c7f0de1c6176ecb280ec012b446efffff293`, from a clean checkout. The configuration digest matches the frozen [registration](registration.md). The host was 13th Gen Intel(R) Core(TM) i3-13100, running Python 3.14.7, PyMongo 4.18.2 and `mongo:9.0.2`.

## Per-case observations

Each row shows the maximum of five repetitions, rounded up to milliseconds. N/A means the registration declares that interval inapplicable. Every row passed. First-hit timestamps come from workers independently of readiness observations, so a safe first hit can precede observed readiness.

| Case                            | Detection (ms) | Safe readiness (ms) | First hit (ms) | Rewarming (ms) |
| ------------------------------- | -------------: | ------------------: | -------------: | -------------: |
| cancellation-during-publication |            N/A |                  10 |              7 |             35 |
| coordinator-pause               |           3349 |                  10 |              9 |             14 |
| coordinator-restart             |            100 |                 147 |            149 |            215 |
| history-loss                    |            N/A |                  21 |             22 |            102 |
| malformed-frames                |            N/A |                 N/A |            N/A |            N/A |
| owner-kill-during-local-hits    |             75 |                 147 |            148 |            219 |
| owner-pause-during-local-hits   |           3253 |                  10 |              9 |             14 |
| reattachment-after-restart      |             80 |                 168 |            169 |            188 |
| shutdown-during-startup         |             28 |                 149 |            151 |            209 |
| slow-reader                     |            N/A |                   2 |              1 |              5 |
| stream-interruption             |            N/A |                  19 |             18 |             26 |
| torn-read-stress                |            N/A |                 N/A |            N/A |            N/A |
| watch-pause                     |           3064 |                   2 |              1 |              7 |
| worker-killed-with-capture      |            N/A |                 208 |            207 |            212 |
| worker-replacement              |            N/A |                 209 |            208 |            213 |

## Interpretation and reproduction

These are observed transition upper bounds for the registered scripted hot set and mixed worker group. Full-set native reads, RPC timeouts, polling and control round trips add observation delay. This run profiles the controller (180.408 seconds of recorded execution), which adds instrumentation overhead; spawned workers are not profiled. It does not measure recovery under version 5's offered load or supersede its failed miss-latency and capacity criteria.

Earlier runs at `a1b188e23255ac8a6ee1269681bea16fb2a4d0cc` and `ab53e506e1056c7d3b36d776b3ff01492734fa57` are withdrawn as complete fault evidence. [PR #276](https://github.com/alessio-locatelli/client-query-cache/pull/276) identified incomplete fencing detection and duplicate idle-worker scenarios in the first, then readiness-gated first-hit evidence in the second. The table uses only the registered full-set, concurrent-read and independent first-hit procedures.

Each coordinator-pause trial retains 16 terminal worker and owner observations, with 4,452–4,457 bytes of serialized probe content (`json.dumps`). Owner-pause trials retain 24 observations including traffic counters, with 5,456–5,465 bytes. Retained state is bounded by operation count, and readiness probes avoid exhaustive residency scans.

## Local traffic preparation

The reproducible regression in `tests/benchmark/stream_cost/test_shared_cache_faults.py::test_local_traffic_prepares_lookup_inputs_once` compares ten sweeps over 64 keys: collection-wrapper and shape preparation each decrease from 640 calls to one, while all 640 native lookups remain.

In the owner-pause trials, median direct-loop hit rates were 517,493/s for synchronous workers and 491,741/s for asyncio workers, versus 53,469/s and 51,470/s in the preceding run at `ab53e506e1056c7d3b36d776b3ff01492734fa57`. Each median uses ten worker samples across five repetitions. A sample is the change in traffic hit count divided by the change in its last-hit timestamp between the retained start and stop observations. Both runs profile only the controller and include control probes in the traffic interval. These scripted native-loop rates do not measure decoded cache-API throughput or isolate every change between the two revisions.

Use the [registered reproduction commands](registration.md#reproduce). For this run, the runner invocation used `python -m cProfile -o <profile> -m benchmarks.stream_cost.shared_cache.run` with the registered arguments. Analysis reports every applicable duration and failure reason per repetition. Raw reports, logs and profiles remain untracked.
