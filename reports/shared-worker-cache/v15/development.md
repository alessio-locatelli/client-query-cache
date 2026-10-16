# Native admissions without data-channel setup

These diagnostics follow [version 14's failure](../v14/results.md). They retain the 1,000 requests/s rate and contribute no acceptance samples.

Three traced sync/eight-worker blocks expose startup work: each worker's first four reads spend about 1.30 ms before the native MongoDB call, versus about 0.127 ms thereafter. Instrumented shared prefix CPU averages 123–126 µs, and post-read CPU averages 117–121 µs. Identity-key preparation, local selection, admission encoding and frame preparation account for about 24, 33, 35 and 42 µs respectively. Instrumentation changes execution cost; these are diagnostic observations, not latency evidence.

A queue-only routing prototype removes every measured selection RPC and data-socket connection in three sync/eight-worker blocks. All nine windows are healthy; cold P99 deltas over direct reads are 0.135, 0.491 and 0.344 ms. Owner CPU is 217–222 µs per request. This motivates explicit native-queue capability and queue-first sending while preserving socket fallback.

The implementation retains each view's default wire shape across identity-key cache eviction. Five alternating 10,000-call batches show essentially unchanged isolated key-pair CPU: cold 0.729 → 0.743 µs and hot 0.403 → 0.399 µs. This cache-lifetime correction does not establish a CPU speedup. Compare `_identity_keys` at `ccf0eb7` and this candidate with fresh 8,192-entry key caches, sequential cold identities and a primed 4,096-identity hot set, using `time.thread_time_ns()` and identical preconstructed inputs.

## Combined preflight

Six balanced cold blocks in all four cells complete with all seventy-two windows healthy. Every shared window admits all 10,000 values through the native queue, with zero measured selection RPCs:

| Model / workers |     P99 deltas over direct ms, blocks 1–6 | Mean ms |
| --------------- | ----------------------------------------: | ------: |
| async / 4       | 0.789, 2.648, 0.427, 0.419, -1.078, 0.290 |   0.583 |
| async / 8       | 0.826, 0.586, 0.445, 0.631, -0.344, 0.852 |   0.499 |
| sync / 4        |  0.657, 1.497, 0.526, 0.400, 1.464, 0.061 |   0.768 |
| sync / 8        | 0.013, -0.147, 0.307, 0.716, 1.178, 0.757 |   0.471 |

Tails remain variable. These point diagnostics cannot establish registered confidence or stability bounds. Reproduce at this candidate by copying its config under `/tmp/agents/`, changing only `phases.cold.blocks` to six, sourcing `scripts/testcontainers-bridge.sh` and running the cold acquisition module with fresh output paths. Subtract direct request P99 from shared request P99 within each balanced block; retain every window and inspect health. Raw output is `v15-six-block-cold.json` under `/tmp/agents/issue-272-continuation/`.

## Discarded alternatives

A cached BSON-frame prefix prototype preserves exact bytes for 10,000 sample admissions but changes isolated median frame CPU only from 1.447 to 1.394 µs. It is not selected.

A single-thread native polling relay prototype completes thirty-six windows healthily. Three-block P99 deltas are async/four 0.422, 0.694, 0.230 ms; async/eight -0.044, 0.946, 0.468 ms; sync/four 0.279, 0.019, 0.543 ms; sync/eight 1.020, 0.487, 0.764 ms. This does not show a robust advantage over the existing relay and is discarded. The registered observer remains unchanged.

Scratch tracers, prototype sources, key/frame timing harnesses and raw outputs remain untracked under `/tmp/agents/issue-272-continuation/`. None contributes to acceptance.
