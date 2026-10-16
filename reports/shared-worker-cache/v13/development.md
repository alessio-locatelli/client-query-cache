# Relay isolation diagnostics

These exploratory diagnostics follow [v12's failed registered study](../v12/results.md) and contribute no acceptance samples. They retain the 1,000 requests/s rate and cannot select rates or alter gates.

Dropping measured owner admissions after startup in three balanced sync/eight-worker blocks gives P99 deltas of 0.658, 1.032 and 0.883 ms, with owner CPU of 72–75 µs per miss. This deliberately removes cache work and cannot be a solution or acceptance evidence. Its limited improvement motivates examining worker-side observer contention.

A nonblocking Python duplex-loop prototype retains byte counters and both TCP legs but gives deltas of 1.071, 1.112 and 0.857 ms in three sync/eight-worker blocks. It is discarded.

A native C relay prototype performs the same blocking receive/send operations outside the Python GIL. It retains TCP_NODELAY, both byte counters and the pause/resume/sever interface. All nine windows complete healthily in each three-block batch:

| Model / workers | P99 delta over direct ms, blocks 1–3 | Owner CPU µs/miss, blocks 1–3 |
| --------------- | -----------------------------------: | ----------------------------: |
| sync / 8        |                  0.579, 0.750, 0.801 |                 234, 242, 238 |
| async / 8       |                  0.565, 0.959, 0.875 |                 210, 214, 214 |

These batches suggest Python relay scheduling contributes to cold tails; they do not establish a causal speedup or registered confidence/stability bounds. The selected observer implementation uses Rust in the existing extension, with one fewer connection thread than the prototype. No C source or raw diagnostic payload is shipped.

## Reproduce the selected mechanism

Build this registration's native extension in release mode. Copy its config under `/tmp/agents/`, changing only `phases.cold.blocks` to three. Source `scripts/testcontainers-bridge.sh`, then run `python -m benchmarks.stream_cost.shared_cache.run --phase cold --only sync:8` or `--only async:8` with the diagnostic config and fresh output paths. Subtract direct request P99 from shared request P99 within each block and divide shared owner CPU by completed requests. Retain every window and check health. This exercises the selected Rust mechanism, rather than reproducing the C prototype's exact implementation.

The C scratch harness, compilation command and raw diagnostic reports remain untracked under `/tmp/agents/issue-272-continuation/`. All required registered phases and timed faults remain mandatory.

## Rust relay and runtime profiles

An initial draft with the Rust observer and v12 cache code runs three balanced blocks in all four cells. All thirty-six windows complete healthily, but the deltas remain variable:

| Model / workers | P99 delta over direct ms, blocks 1–3 |
| --------------- | -----------------------------------: |
| async / 4       |                  1.210, 0.379, 1.075 |
| async / 8       |                  0.691, 0.466, 1.523 |
| sync / 4        |                  0.468, 0.356, 0.326 |
| sync / 8        |                  0.949, 1.064, 0.775 |

A separate three-block async/eight-worker trace records wall and thread CPU timestamps around native MongoDB reads and admission sends. Shared worker prefix CPU averages about 126–132 µs per request, with P99 about 258–275 µs; post-read CPU averages about 88–93 µs, with P99 about 192–215 µs. The corresponding direct path averages about 8 µs before and 17–20 µs after the read. Instrumentation changes execution cost and cannot contribute latency evidence. Profiles identify integer-key serialization, scalar classification and remaining namespace generator contexts as additional work.

The updated draft removes the namespace generator contexts and reuses fixed integer key envelopes. Five alternating 10,000-admission batches with 4 KiB encoded values, a 100 MiB budget, a 1 MiB entry cap and precreated namespace give median process CPU costs of **9.930 µs with v12's manager and 7.826 µs with guarded namespace contexts**. This excludes the shared publisher and MongoDB. Reproduce the core part of the [v10 harness](../v10/development.md#reproduce) at `3d2ec25` and this candidate, setting that budget/cap and calling `core.create_namespace(namespace)` before timing.

Five 10,000-call integer-key batches give median process CPU of **0.816 → 0.114 µs for encoding** and **0.548 → 0.122 µs for decoding**. Compare `encode_key` and `decode_key` at `3d2ec25` with this candidate, using integers `range(10000)`, their preconstructed encoded keys, `time.process_time()` and the median of five batches. Include loop overhead consistently. The fixed BSON envelope is derived once from the official encoder; these isolated costs do not estimate request-tail improvements.

## Combined candidate preflight

After the namespace-context and integer-key changes, six balanced cold blocks per cell complete with all seventy-two windows healthy. The offered rate remains 1,000 requests/s and every other workload setting remains fixed:

| Model / workers |     P99 delta over direct ms, blocks 1–6 | Mean ms |
| --------------- | ---------------------------------------: | ------: |
| async / 4       | 0.656, 1.054, 0.465, 0.796, 1.095, 0.386 |   0.742 |
| async / 8       | 0.556, 0.712, 0.735, 0.854, 0.002, 0.960 |   0.637 |
| sync / 4        | 0.716, 0.543, 0.549, 0.516, 0.249, 0.772 |   0.558 |
| sync / 8        | 0.634, 0.570, 0.584, 0.947, 0.761, 0.653 |   0.691 |

These point diagnostics motivate freezing the complete candidate. They do not establish the registered upper bounds or stability, and none of their windows contributes to acceptance. Reproduce using the selected-mechanism commands above with six blocks and all four cells (omit `--only`). The raw report is retained untracked as `v13-optimized-diagnostic-cold.json` under `/tmp/agents/issue-272-continuation/`.
