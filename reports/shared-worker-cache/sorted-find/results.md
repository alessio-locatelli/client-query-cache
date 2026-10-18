# Bounded sorted-find publication

[Issue #290](https://github.com/alessio-locatelli/client-query-cache/issues/290) is resolved by an implemented research optimization and a measured limit on expanding its public scope. Fully consumed positive-limit results can be read locally by another worker without owner selection. The small sorted working set does not produce the required group-memory saving, so these results do not justify public promotion. Functional public cursor coverage remains tracked by [#295](https://github.com/alessio-locatelli/client-query-cache/issues/295).

## Provenance and decision boundary

The final measured library and collector source is `108cc371f542e281e57d84fed66e2aebead70edf`; the main comparison is `5af2d8b210a42ef2619fb2a4e895e36c6fb7d243`. The final experiment started with a clean source tree. The delivered tree subsequently narrows local native-token annotations to nonnegative integers; the affected method bytecode is unchanged. [Protocol A](protocol.md) reuses v15's workload and recorded failures; [protocol B](protocol-b.md) registers the final source and additional identity diagnostics. Neither is a production-promotion campaign.

The [v15 report](../v15/results.md#reproduction-and-evidence-limits) says its raw acquisitions and profiles were lost. Its recorded upper bounds motivated this investigation; they cannot independently verify a speedup against v15. Candidate A (`581f60f`) completed eighteen diagnostic windows and removed measured selection RPCs, but retained the memory shortfall. Its three sync memory/CPU/P99 ratios to independent caches were 1.041/1.026/1.050, 1.040/1.070/1.070 and 1.040/1.054/1.046; async ratios were 1.036/1.024/1.021, 1.036/0.805/1.064 and 1.035/1.034/1.092. These are development point estimates, not confidence bounds, and are excluded from the final table.

Measurements use CPython 3.14.7, PyMongo 4.18.2, psutil 7.2.2, Testcontainers 4.15.0 and Fedora Linux 7.2.10 on an Intel Core i3-13100 with eight logical CPUs. MongoDB is `mongo:9.0.2@sha256:bac22ea7710d774103dcad3ec8ac13cba1eb378f488e3ce8a6b3a1adf2ba9dcc`. The unchanged release extension has SHA-256 `e82a6b09192805fabebb8746655cabfd213d7cccbc1f957f810e4d4c4cf06556`, rustc 1.99.0 (`b940084d7`, 2026-09-28), Maturin 1.15.0, `cp314-abi3-linux_x86_64`, and Cargo.lock SHA-256 `78496ae54147678e169f504e4094bd984ce34c1ce33a3bd890619ef93c2913b9`. Baseline and candidate use the same native binary; library distribution metadata is 0.8.1. Rebuilds must record their own digest rather than assume byte identity.

## Sorted results

The [configuration](config.json) restricts v15 sensitivity to `find16`: 16,384 documents, 64 categories, 4 KiB payloads and 16 sorted results. Each of three balanced blocks runs direct MongoDB, independent caches and shared publication in both models, with eight workers, four in-flight reads per worker and a fixed aggregate 319 requests/s for 32 seconds after ten seconds of warmup. MongoDB has two CPUs and a 2 GiB cgroup limit.

| Model / block | Path         | Group PSS, MiB | CPU, µs/read | P50, ms | P95, ms | P99, ms | Harness CPU, µs/read |
| ------------- | ------------ | -------------: | -----------: | ------: | ------: | ------: | -------------------: |
| sync / 1      | direct       |         358.15 |      3304.94 |   3.308 |   4.889 |   6.003 |               252.74 |
| sync / 1      | independent  |         390.04 |       986.28 |   0.885 |   1.138 |   1.306 |               301.72 |
| sync / 1      | shared-index |         405.91 |      1042.27 |   0.969 |   1.219 |   1.393 |               325.24 |
| sync / 2      | direct       |         358.12 |      3355.38 |   3.331 |   4.965 |   6.064 |               250.78 |
| sync / 2      | independent  |         390.10 |       999.20 |   0.901 |   1.191 |   1.350 |               305.64 |
| sync / 2      | shared-index |         405.73 |      1032.25 |   0.961 |   1.213 |   1.385 |               320.34 |
| sync / 3      | direct       |         358.06 |      3405.72 |   3.415 |   5.277 |   6.847 |               252.74 |
| sync / 3      | independent  |         390.03 |       976.31 |   0.910 |   1.217 |   1.379 |               301.72 |
| sync / 3      | shared-index |         406.01 |       990.04 |   0.960 |   1.282 |   1.472 |               300.74 |
| async / 1     | direct       |         354.92 |      3886.43 |   4.245 |   6.241 |   7.550 |               260.58 |
| async / 1     | independent  |         388.87 |      1149.71 |   1.540 |   2.083 |   2.395 |               306.62 |
| async / 1     | shared-index |         402.71 |      1168.97 |   1.618 |   2.154 |   2.464 |               314.46 |
| async / 2     | direct       |         354.79 |      3733.62 |   4.035 |   7.364 |   9.366 |               257.64 |
| async / 2     | independent  |         389.12 |      1032.83 |   1.418 |   2.182 |   2.493 |               270.38 |
| async / 2     | shared-index |         403.01 |      1251.19 |   1.665 |   2.270 |   2.566 |               327.19 |
| async / 3     | direct       |         354.72 |      3963.94 |   4.265 |   6.796 |   8.494 |               265.48 |
| async / 3     | independent  |         389.11 |      1196.46 |   1.588 |   2.174 |   2.530 |               308.58 |
| async / 3     | shared-index |         402.88 |      1181.07 |   1.607 |   2.153 |   2.455 |               323.28 |

CPU includes workers, owner and MongoDB, including drain work; the harness is reported separately. Group memory is proportional set size (PSS), including the owner and counting shared pages once; MongoDB cgroup memory is separate. P99 concerns complete application requests, including the workload's result verification. All values are descriptive per-window measurements; no request pooling or promotion inference is used.

All eighteen windows were healthy and completed 10,208 requests each. Every cached window had 10,208 hits and zero misses, all inside the measurement window. Three direct windows completed their last request during drain. Each shared window recorded zero selection requests, owner-served hits and data-channel IPC bytes; native recency notifications still ran. Wire traffic per window was 719,481,513 bytes direct, 188,848 independent and 60,902 shared. MongoDB cgroup memory grew from 180.47 to 639.66 MiB across the reused container, so those snapshots cannot establish a path-specific total-memory saving.

Shared/independent point ratios were 1.040–1.041 for sync group PSS and 1.035–1.036 for async. CPU ratios were 1.014–1.057 sync and 0.987–1.211 async; the middle async block exceeded the 1.10 CPU criterion. P99 ratios were 1.026–1.068 sync and 0.971–1.029 async. These point outcomes retain the memory failure and CPU variation; they do not replace v15's confidence/stability gates.

The memory target is at most 0.75 times independent group PSS. The sync target was approximately 292.5 MiB against direct workers at 358.1 MiB; the async target was approximately 291.8 MiB against direct workers at 354.8 MiB. A payload-only optimization cannot reach that target under these observed spawn-based worker footprints. Removing owner RPCs cannot remove the workers' baseline footprint. Shared ownership adds an owner process and index to save only seven duplicate copies of this 4.264 MiB encoded result catalogue. The byte budget is a capacity bound, not evidence of resident memory savings. A native namespace-generation field would improve invalidation complexity but would not remove this fixed footprint. Another coordination or fallback architecture is not justified by these observations.

A local hit copies a 69,853–69,871-byte encoded result before decoding its sixteen documents. A separate async profile retained eight worker files per baseline and eight plus the owner for shared publication. It traced 10,208 native local lookups and 163,328 result checksums. Instrumented cumulative time across workers was 1.019 seconds for native lookup, 1.142 seconds for canonicalization and 1.297 seconds for checksum verification. These overlapping profile times are excluded from latency comparisons. An initial profile helper stripped process IDs and overwrote worker summaries; that output is excluded, and the corrected helper retains each process.

## Write safety and cost

The core remains authoritative for admission, eviction and invalidation. Publications occur only after complete consumption. Exact local hits use the existing namespace epoch, incarnation, progress, availability and payload-copy checks; missing local results and compatible larger-limit reuse retain owner selection. Writes remove all published find payloads for their collection while preserving unrelated identity hits. Tests cover both sync and async separate-process readers, empty results, isolated snapshots, partial close, write/capture races, unportable codecs, zero/negative limits and generated ordering of invalidation, admission, eviction, resets and outages.

The isolated [invalidation diagnostic](../../../research/sorted_find/invalidation.py) fills results outside timing, measures `record_write` with native publication enabled, then asserts no result publication remains. Each encoded result is 66,051 bytes. Five batches use 500, 100 or 20 writes per batch at the following cardinalities; timer overhead remains included. Publisher and core code are identical between candidates A and B, so these candidate-A measurements are reused.

| Published result shapes | Median CPU per write, µs | Median elapsed per write, µs |
| ----------------------- | -----------------------: | ---------------------------: |
| 1                       |                    2.648 |                        2.275 |
| 64                      |                   20.760 |                       20.079 |
| 1,024                   |                  454.305 |                      454.294 |

Invalidation is linear in published shapes. At the measured 64-shape working set its isolated cost does not justify changing the native layout; it becomes material at higher cardinality. These values exclude MongoDB writes, stream delivery and end-to-end write churn, and cannot establish a lag or throughput guarantee. Public broader-read delivery in #295 must evaluate its own write workload and sizes. No further full capacity, active or timed-fault campaign was run for this non-promoted research path.

## Existing identity reads

The public runner compared main and candidate at four workers, 4,096 warmed 4 KiB documents and 2,000 samples per worker, retaining three repetitions and direct/independent/shared paths for hot and cold reads. CPU includes owner and worker processes; this runner does not include MongoDB CPU, unlike the sorted collector above.

| Model / workload | Source | CPU median [range], µs/read |     P99 median [range], µs | Group PSS median, MiB |
| ---------------- | ------ | --------------------------: | -------------------------: | --------------------: |
| sync / hot       | main   |         18.05 [9.17, 22.16] |       32.65 [16.01, 42.44] |                252.38 |
| sync / hot       | final  |          9.78 [9.71, 12.45] |       14.30 [12.18, 19.41] |                252.22 |
| sync / cold      | main   |     217.52 [207.52, 225.35] |    517.01 [455.94, 937.77] |                280.80 |
| sync / cold      | final  |     217.44 [215.22, 225.62] |    610.58 [548.10, 945.35] |                280.48 |
| async / hot      | main   |         13.20 [7.92, 18.42] |        17.63 [9.29, 33.20] |                253.88 |
| async / hot      | final  |        13.17 [12.03, 13.36] |       22.31 [20.33, 25.77] |                253.50 |
| async / cold     | main   |     339.12 [334.97, 346.46] | 1114.46 [1070.30, 1369.78] |                282.35 |
| async / cold     | final  |     343.28 [342.43, 368.87] |  1018.95 [925.70, 1759.92] |                281.80 |

The initial candidate-A hot medians were 26.78 µs CPU/read sync and 16.07 µs async, while its cold medians were 213.70 and 320.81 µs. Final cold CPU medians were 217.44 and 343.28 µs, versus main's 217.52 and 339.12 µs. Short hot-window CPU and tail latencies varied widely, including unchanged baseline paths. The final sync cold P99 range overlaps main; the final async run includes a 1.760 ms tail. These observations are retained without claiming that the historical cold confidence bounds have been requalified.

The [alternating native-state diagnostic](../../../research/sorted_find/hot.py) loads main's adapters from the immutable comparison commit and the candidate adapters into one process, using the same real native state, PyMongo client settings and one primed document. It takes ten alternating 20,000-hit batches after 10,000 warmup hits per source and model. It isolates adapter/native hit CPU and excludes MongoDB, owner processing and multiprocess scheduling.

| Controlled run | Sync main / candidate CPU, µs/hit | Async main / candidate CPU, µs/hit |
| -------------- | --------------------------------: | ---------------------------------: |
| 1              |                   5.0220 / 5.0526 |                    5.3272 / 5.3433 |
| 2              |                   4.9827 / 5.0268 |                    5.2476 / 5.2100 |
| 3              |                   5.0745 / 5.0831 |                    5.3129 / 5.3251 |
| 4              |                   5.0648 / 4.9707 |                    5.3091 / 5.2917 |

The controlled script drains recency tokens outside timing and asserts no drops in each batch. Earlier scratch runs allowed the ring to fill; their mixed enqueue/drop observations are excluded. Across the controlled runs, sync median differences were −0.094–+0.044 µs and async differences −0.038–+0.016 µs. Interleaved batch differences crossed zero. An initial same-view helper-swap diagnostic gave main/candidate medians of 4.9400/4.9560 µs sync and 5.1524/5.1858 µs async. The retained `--same-view` mode gave 5.0832/5.0780 µs sync and 5.2775/5.2563 µs async. Both comparisons had mixed signed batch differences. The supported helper retains its original calling convention and adds no executed work on a hot identity hit. These small observations do not isolate a stable hot-path regression; source layout and short-run variation remain part of their uncertainty.

The [longer hot-window diagnostic](../../../research/sorted_find/hot_window.py) reuses the public runner's shared window with 100,000 samples per worker. Two main runs gave sync CPU of 6.846/7.033 µs/read and P99 of 10.316/20.609 µs; async CPU was 7.453/7.471 µs and P99 10.047/23.222 µs. Candidate A gave 7.068/7.426 µs CPU and 20.269/17.505 µs P99 (sync/async). The final candidate gave 6.982/7.517 µs CPU and 19.119/20.615 µs P99. Every window served 400,000 shared hits. These longer observations expose tail variation in main itself and do not establish a consistent candidate slowdown. Their larger retained latency arrays also change the collector's memory footprint, so memory is compared only at matching sample counts.

## Reproduce

Run from the delivered PR tree, whose executable library paths, collector and configuration match the frozen revision above; the retained diagnostic scripts are linked above. Keep raw output outside version control. From a clean checkout, build the release extension using the project's `uv run -- maturin develop --release --locked` command, then source `scripts/testcontainers-bridge.sh`.

```bash
mkdir -p /tmp/agents/sorted-find-reproduction
uv run -- python -m benchmarks.stream_cost.shared_cache.run --config reports/shared-worker-cache/sorted-find/config.json --phase sensitivity --output /tmp/agents/sorted-find-reproduction/sorted.json
uv run -- python -m benchmarks.public_shared_cache --repetitions 3 --samples 2000 --output /tmp/agents/sorted-find-reproduction/identity.json
PYTHONPATH=src:. uv run -- python research/sorted_find/hot.py > /tmp/agents/sorted-find-reproduction/identity-isolated.json
PYTHONPATH=src:. uv run -- python research/sorted_find/hot.py --same-view > /tmp/agents/sorted-find-reproduction/helper-swap.json
PYTHONPATH=src:. uv run -- python research/sorted_find/hot_window.py /tmp/agents/sorted-find-reproduction/identity-longer.json
uv run -- python research/sorted_find/invalidation.py > /tmp/agents/sorted-find-reproduction/invalidation.json
TMPDIR=/tmp/agents/sorted-find-reproduction uv run -- python -m benchmarks.stream_cost.shared_cache.diagnostics --config reports/shared-worker-cache/sorted-find/config.json --profile sensitivity 8 async --output /tmp/agents/sorted-find-reproduction/profiles.json
```

Run the public identity runner again from the main comparison checkout with its own matching import path and dependency environment. For the longer diagnostic, pass the delivered tree's absolute `research/sorted_find/hot_window.py` path while importing the baseline checkout. For a shared environment, prepend that checkout's `src` and root to `PYTHONPATH` and verify `client_query_cache._shared.adapters.__file__`; the baseline run here did so and used the same extension binary. Do not compare different dependency or native builds silently.

For the sorted report, inspect every cell's `healthy`, completion and outcomes, then call `benchmarks.stream_cost.shared_cache.analysis.block_statistics(cell)`. Convert `steady_pss` to MiB, `cpu_per_request` to µs and `request_p99` to ms. Subtract owner before/after counters to verify no measured RPC or data-channel IPC. For public identity reports, divide `measured_cpu_seconds` by `4 * samples_per_worker` and add worker/owner PSS for group memory. For profiles, retain all worker IDs; cumulative times overlap and must not be added.

Raw observations are intentionally untracked and are not durable evidence for recomputing these exact tables after temporary storage is lost. The committed sources, configuration and commands collect fresh comparisons; they do not independently verify the original statistics.
