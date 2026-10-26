# Rust find-key encoding

This correction belongs to [#341](https://github.com/alessio-locatelli/client-query-cache/issues/341). The [baseline report](results.md) defines workload and measurement limits; [the plan](plan.md#rust-key-preparation-correction) registers the comparison. These measurements do not requalify historical full protocols.

## First Rust comparison: withheld

The installed candidate is [`39ea08d74a3618f2d251cb3166a488b72200082b`](https://github.com/alessio-locatelli/client-query-cache/commit/39ea08d74a3618f2d251cb3166a488b72200082b), native SHA-256 `5e77cecc4a7c6fa4bb14caf176c3355742bba382214c8df0f94ede6d298d3785`. Main remains the clean 0.9.1 baseline. Python/dependency versions and isolated import origins match, including normal environment loading for the test command. No build or test overlaps read timing.

All 48 windows have expected hits/misses, zero bypasses and one stream. Cold sorted reads retain 1,024 synchronous owner selections in both builds; hot reads select locally. Cells are median [minimum, maximum] across three windows.

| API / build       |       Cold sorted P50 µs |      Reader CPU µs/read |           Group PSS MiB |                    Reads/s |
| ----------------- | -----------------------: | ----------------------: | ----------------------: | -------------------------: |
| sync / main       |  804.30 [789.71, 829.38] | 815.12 [799.03, 852.50] | 243.53 [243.37, 243.56] | 3803.00 [3738.62, 3848.07] |
| sync / candidate  |  754.21 [748.15, 770.89] | 761.78 [714.91, 813.74] | 243.84 [243.78, 243.86] | 4077.41 [3908.54, 4245.11] |
| async / main      |  936.55 [934.31, 946.79] | 976.84 [967.37, 979.15] | 244.99 [244.94, 245.04] | 3495.05 [3371.99, 3524.11] |
| async / candidate | 900.03 [898.78, 1026.23] | 929.34 [927.35, 997.07] | 245.20 [245.14, 245.22] | 3548.38 [3118.79, 3689.22] |

Sync cold sorted P50 falls in all three pairs (2.4–9.8%) and reader CPU falls 4.5–10.5%. Async results vary: two P50/CPU pairs improve, one is slower; tails have mixed directions. Sync identity cold P99 is lower in every pair, so this cohort does not repeat the rejected filter's identity cold tail finding.

Acceptance remains blocked. Sorted group PSS is higher in all twelve hot/cold pairs (0.08–0.41 MiB), and existing-test time is higher in all three pairs. The same 279 cases take 70.52 [70.27, 70.60] seconds on main and 70.82 [70.67, 71.08] on the candidate; paired increases are 0.56, 0.22 and 0.40 seconds. Sync identity hot throughput is also lower in every pair, although ranges overlap substantially: 412,847 [393,838, 541,972] versus 392,269 [333,522, 525,041] reads/s. These findings are retained rather than hidden by encoding improvements.

Five separate cold-key floor pairs prepare 10,000 distinct canonical families per batch without retained-key hits. Main spends 25.32 [25.00, 25.87] µs/query; Rust spends 7.29 [7.14, 7.54], about 71% less. This includes binding/cache preparation and does not imply a 71% MongoDB-read improvement.

All four worker profiles per build/model were aggregated in separate 256-call windows. Each 1,024-read window has 67,584 Python `to_wire` calls on main versus 3,072 specialized-scalar callbacks on the candidate, plus 1,024 native encoder calls. Both retain 16,384 cursor appends and 2,048 frame encodings. Four transport diagnostics have identical worker traffic: 1,024 selection requests, 1,024 admissions, 69,139,456 bytes sent and 66,560 received. All timeout/failure/drop counters are zero. Rust removes query traversal, not the existing selection or result transport.

Three separate fresh-process import probes per build show overlapping CPU ranges (main 101.08–107.24 ms, candidate 101.41–102.90 ms) and PSS ranges (35.48–35.54 versus 35.53–35.59 MiB). They do not isolate the cause of the complete-test timing difference. Inspection identifies eager native type/encoder initialization on processes that never encode a find. The registered correction removes that unnecessary work and the per-process tag hash table; only its fresh measurements can establish acceptance.

## Initialization correction and generic paths

The next installed source is [`5bfff311f0973f4c22f36a18eb0f6277d07164ef`](https://github.com/alessio-locatelli/client-query-cache/commit/5bfff311f0973f4c22f36a18eb0f6277d07164ef), native SHA-256 `6147a644d42fba48cf674342f748697d228affabc40ac7b1b3f68bb4e19ecbc5`. Encoder type/instance construction now occurs only when encoding a find. Native instances retain no Python callback. Fresh-process checks confirm generic key encoding does not initialize the encoder.

Its full 48-window comparison has expected cache outcomes. Sync cold sorted P50 falls in all three pairs (0.8–7.9%), and reader CPU falls 4.4–14.8%. Async and hot results vary. Sorted PSS still increases 0.12–0.34 MiB. Existing-test elapsed medians are 71.10 [70.82, 71.78] seconds for main and 70.83 [70.82, 71.78] for the candidate, with mixed paired directions. These observations do not qualify the subsequent allocation correction.

The generic identity results below belong to this source, not the final wheel. The subsequent source changes only the find-cache method: generic methods/adapters and the native binary are identical. Cells retain all three window statistics.

| API / workload / build   |                  P50 µs |                  P95 µs |                     P99 µs |      Worker CPU µs/read |    Owner CPU µs/read |  MongoDB CPU µs/read |           Group PSS MiB |                          Reads/s |
| ------------------------ | ----------------------: | ----------------------: | -------------------------: | ----------------------: | -------------------: | -------------------: | ----------------------: | -------------------------------: |
| sync / hot / main        |       7.59 [5.63, 7.63] |    19.85 [18.10, 31.45] |       27.49 [21.67, 37.75] |     10.06 [8.30, 11.39] |    0.31 [0.31, 0.92] |    0.17 [0.03, 0.61] | 212.88 [212.82, 212.97] | 366259.89 [296677.11, 444266.15] |
| sync / hot / candidate   |       6.42 [6.01, 7.50] |    23.47 [23.08, 27.51] |       29.48 [28.48, 31.15] |       9.70 [9.09, 9.97] |    0.61 [0.61, 1.53] |    0.02 [0.01, 0.03] | 213.01 [212.92, 213.14] | 366071.83 [364519.78, 384949.32] |
| async / hot / main       |       6.32 [6.21, 8.29] |     25.54 [9.06, 35.94] |       33.58 [11.02, 38.21] |      9.76 [7.74, 11.18] |    0.61 [0.61, 1.53] |    0.02 [0.01, 0.03] | 214.14 [214.05, 214.38] | 397631.96 [348317.60, 441149.64] |
| async / hot / candidate  |       8.46 [6.64, 8.63] |    27.59 [12.06, 30.06] |       35.09 [15.47, 37.05] |     10.69 [9.36, 11.44] |    0.61 [0.31, 1.53] |    0.02 [0.01, 0.02] | 214.19 [214.02, 214.23] | 332166.85 [307150.20, 420445.00] |
| sync / cold / main       | 232.73 [231.53, 241.63] | 579.86 [288.43, 662.60] |  1103.10 [402.34, 1311.82] | 186.14 [166.74, 197.61] | 43.95 [36.62, 46.39] | 61.05 [51.98, 62.63] | 237.11 [237.08, 237.20] |    14152.73 [13294.67, 16795.43] |
| sync / cold / candidate  | 238.76 [232.39, 239.69] | 676.94 [415.78, 778.82] |   994.66 [629.36, 1154.10] | 190.39 [175.61, 198.65] | 43.95 [39.06, 46.39] | 61.30 [55.29, 64.28] | 237.24 [237.20, 237.67] |    14064.83 [14035.66, 15152.78] |
| async / cold / main      | 323.37 [319.88, 330.00] | 936.21 [918.67, 937.31] | 1548.83 [1458.41, 1554.66] | 324.17 [317.30, 328.41] | 51.27 [48.83, 51.27] | 64.94 [64.77, 67.24] | 238.45 [238.37, 238.51] |      9919.92 [9623.27, 10185.14] |
| async / cold / candidate | 319.50 [319.48, 328.97] | 859.04 [822.26, 891.69] | 1419.70 [1222.47, 2005.43] | 318.86 [304.11, 321.95] | 48.83 [48.83, 53.71] | 63.86 [60.63, 65.34] | 238.48 [238.47, 238.58] |     10000.58 [9638.60, 10157.35] |

Async identity hot P50 is higher in all three pairs, despite overlapping ranges; that specific signal uses the reserved controls below. Other identity latency/CPU directions vary. Fresh import probes have main CPU 100.01–101.11 ms and candidate CPU 102.51–103.80 ms; PSS is 35.50–35.55 versus 35.53–39.74 MiB, including the high candidate outlier. They are separate startup observations, not read-timing or peak-memory qualifications. No startup benefit is claimed.

## Allocation correction on find reads

This cohort uses installed source [`5913ef1ef6c39d76a98adf74e7dc413fdc1b5c99`](https://github.com/alessio-locatelli/client-query-cache/commit/5913ef1ef6c39d76a98adf74e7dc413fdc1b5c99). Its native binary is byte-identical to the preceding source. The private cache uses the canonical family/limit pair directly; the canonical sequence wrapper exists only in the actual wire key. This removes a retained tuple per query and repeated wrapper construction. Retained encoding counts and the per-key byte bound remain unchanged.

The fresh comparison contains exactly 24 sorted windows. Every hot call hits locally, every cold call misses, bypasses are zero and there is one stream. Cold windows retain 1,024 owner selections; hot windows retain zero. No build, test or other measurement campaign overlaps read timing.

| API / workload / build   |                   P50 µs |                     P95 µs |                     P99 µs |      Worker CPU µs/read |       Owner CPU µs/read |     MongoDB CPU µs/read |           Group PSS MiB |                       Reads/s |
| ------------------------ | -----------------------: | -------------------------: | -------------------------: | ----------------------: | ----------------------: | ----------------------: | ----------------------: | ----------------------------: |
| sync / hot / main        |     79.11 [72.81, 85.32] |     100.44 [92.75, 234.01] |    244.21 [161.10, 376.96] |   81.65 [68.70, 105.84] |       2.44 [0.00, 2.44] |       0.35 [0.17, 0.36] | 210.80 [210.60, 211.02] | 40359.60 [35918.74, 45095.25] |
| sync / hot / candidate   |     48.02 [43.67, 65.75] |    197.27 [161.45, 199.69] |    236.03 [218.62, 252.40] |    81.84 [65.17, 85.29] |       2.44 [0.00, 2.44] |       0.13 [0.10, 0.14] | 211.14 [211.09, 211.15] | 45786.76 [43063.54, 58477.04] |
| async / hot / main       |     50.77 [50.10, 74.66] |    261.51 [194.06, 268.43] |    374.62 [264.53, 376.75] |    85.76 [76.75, 95.56] |       2.44 [2.44, 2.44] |       0.18 [0.15, 3.82] | 212.43 [212.23, 212.44] | 45064.92 [39298.75, 47647.34] |
| async / hot / candidate  |     51.32 [48.96, 84.32] |    200.46 [109.57, 296.95] |    323.06 [302.17, 375.37] |    81.44 [77.95, 90.32] |       2.44 [0.00, 2.44] |       0.19 [0.18, 0.23] | 212.62 [212.61, 212.63] | 40640.57 [36549.06, 42291.88] |
| sync / cold / main       |  879.28 [780.97, 887.17] | 1891.40 [1377.87, 2800.18] | 3336.64 [2131.49, 5759.26] | 559.61 [526.24, 652.32] | 195.31 [175.78, 224.61] | 172.76 [162.45, 206.02] | 243.61 [243.56, 243.69] |    3967.24 [3536.57, 4182.29] |
| sync / cold / candidate  |  748.94 [718.13, 800.32] | 2091.99 [1132.89, 2614.11] | 2777.48 [1376.61, 3379.95] | 548.33 [447.70, 554.45] | 205.08 [166.02, 205.08] | 171.41 [155.84, 183.16] | 243.82 [243.79, 243.85] |    4051.23 [4021.30, 5024.92] |
| async / cold / main      | 986.36 [927.75, 1034.88] | 1885.51 [1350.59, 2826.21] | 3001.05 [2014.57, 4009.13] | 699.93 [680.50, 839.66] | 185.55 [185.55, 224.61] | 172.78 [160.36, 214.12] | 245.08 [244.96, 245.08] |    3475.96 [3118.81, 4016.36] |
| async / cold / candidate |  935.86 [929.71, 946.19] | 2892.25 [2506.52, 3278.60] | 4094.06 [3846.18, 4100.51] | 785.54 [702.46, 807.95] | 224.61 [205.08, 234.38] | 202.89 [177.57, 205.85] | 245.20 [245.10, 245.22] |    3221.14 [3220.07, 3669.30] |

Sync cold P50 decreases in every pair, by 8.0–14.8%. Reader CPU and tail/throughput directions vary. Async cold P95 is higher in all three final pairs and async hot throughput is lower in all three; related latency/CPU directions vary, ranges overlap, and the preceding cohorts do not reproduce uniform directions. These uncertain negative signals remain in the tables. No universal end-to-end, hot-read or tail improvement is established.

Sorted group PSS increases in all twelve pairs by 0.12–0.49 MiB (at most 0.23%). The redundant per-query wrapper is removed and the encoded-key budget is preserved. Live PSS includes compiled code, native/Python metadata and allocator residency; this experiment does not isolate their individual contributions. This CPU correction is not a memory-saving claim. Peak memory and large-query encoding costs are not qualified.

### Identity hit controls

Six alternating revision pairs use async identity hot reads, 1,024 warm keys and 8,192 calls per worker. All twelve windows have 32,768 local hits, zero misses/bypasses/owner requests and one stream. They are a separate acquisition, not pooled with the preceding three windows.

| Build     |            P50 µs |              P95 µs |               P99 µs |  Reader CPU µs/read |           Group PSS MiB |                          Reads/s |
| --------- | ----------------: | ------------------: | -------------------: | ------------------: | ----------------------: | -------------------------------: |
| main      | 8.21 [6.04, 8.60] | 20.59 [8.97, 28.23] | 26.82 [10.54, 37.51] | 10.32 [7.30, 12.67] | 214.24 [214.08, 214.43] | 388805.42 [296743.74, 452301.80] |
| candidate | 8.19 [5.70, 8.67] | 15.22 [9.38, 35.46] | 19.63 [11.47, 37.94] |  8.97 [7.78, 13.90] | 214.33 [214.25, 214.45] | 414233.74 [286911.40, 516555.63] |

Three paired P50 changes are positive and three negative (−33.7% to +35.8%); this control does not reproduce the earlier uniform median increase. Separate 256-call profiles aggregate all four workers per build: each has 1,024 native lookups and 1,024 generic key-cache calls, with no find encoder use. Instrumented durations are excluded from these timing statistics.

### Encoding work and transport

The final five encoding-floor pairs spend 25.93 [25.37, 26.81] µs/query on main and 6.43 [6.41, 7.05] on the candidate: about 75% less preparation CPU. The corpus, cache limits and byte checks follow the registered diagnostic. This is a binding/cache preparation floor, not a MongoDB latency percentage.

Final cold worker profiles retain 1,024 native encodings and 3,072 specialized-scalar Python callbacks per 1,024 reads, versus 67,584 Python `to_wire` calls on main. Separate async hot profiles show cached keys with no native encoding, Python wire traversal or selection frames. The correction removes preparation work; result snapshots and BSON decoding remain.

All four final cold transport diagnostics retain the same 1,024 selections, 1,024 admissions and worker byte counts as the first Rust cohort, with zero failure/timeout/drop counters. The owner protocol and result transport are identical.

### Existing-test timing and startup state

The first final-source timing cohort has main 71.37 [70.61, 72.15] seconds and candidate 72.14 [71.13, 73.21], with paired increases 1.06, 0.77 and 0.52 seconds. It is retained as unbalanced acquisition evidence: the first candidate run writes 483 bytecode-cache files while baseline and later candidate runs write none. Its external-minus-pytest duration is 1.19 seconds, versus 0.48–0.53 seconds in the other runs.

A separate per-test duration attribution sums concurrent phases across the four workers: main/candidate call time 36.63/36.17 seconds, setup 46.43/48.20 and teardown 149.55/151.59. These are not wall-clock totals. Individual teardown differences have both signs, including +1.06, −0.81 and −0.67 seconds; they do not isolate a cached-read slowdown.

The replacement comparison warms plugin/test imports with the same collection-only command in both installed environments. All six timed runs select the same 279 existing cases and have no failures or warnings. Main elapsed time is 71.56 [70.88, 71.95] seconds; candidate is 71.13 [70.70, 72.14]. Paired differences are +0.25, +0.19 and −0.86 seconds. Startup/exiting overhead is 0.49 seconds for main and 0.47–0.51 for the candidate. No reproducible existing-test slowdown or speedup is established by the balanced comparison.

### Scope of the correction

The implementation removes demonstrated duplicate serialization and lowers preparation CPU. It retains authoritative selection, cursor behavior and consistency fences. The report preserves the memory cost and uncertain end-to-end results; the isolated CPU gain does not qualify historical full protocols or promise every workload improves. Acceptance uses the explicit user approval recorded below.

## Final review correction and acceptance

The final review also found that plain `int` and BSON `Int64` limits compare equal in a Python dictionary despite having different wire keys. Source [`61d0ab56105a81174a6a93e9ef7ab2ed512b5e8f`](https://github.com/alessio-locatelli/client-query-cache/commit/61d0ab56105a81174a6a93e9ef7ab2ed512b5e8f) distinguishes specialized limit types in the private cache key. The ordinary integer pair remains unchanged and avoids a redundant canonicalization call. Generated same-cache tests reproduce the defect in both call orders before the fix and pass after it, including repeated hits.

The corrected clean release has identical native bytes and matched installed dependencies/import origins. Five fresh alternating floor pairs spend 25.63 [24.82, 26.44] µs/query on main and 6.47 [6.18, 6.95] on the candidate, about 75% less preparation CPU. All builds and tests finish before floor timing. These measurements qualify only the corrected preparation path; the end-to-end, resource and existing-test timing tables above remain attributed to their frozen sources.

On 2026-10-26, the user explicitly accepted the measured 0.12–0.49 MiB worker-group memory increase (at most 0.23%) and uncertain async performance results in exchange for the preparation CPU reduction. This approval applies to the Rust encoding correction; the rejected native selection trials remain withheld. The user also authorized one additional final review beyond the ten-call cap, covering the limit correction, CI/test fixes and final artifacts. Main-spec synchronization and archival require that review to pass.

## Validation boundary

The Python coverage gate reaches 100% with strict-no-cover. Native wire-byte, specialized scalar, stack-guard, budget and cursor cases are exercised; this does not claim complete native coverage ([#328](https://github.com/alessio-locatelli/client-query-cache/issues/328)). One earlier full-suite TCP recovery timeout passed in isolation and on the complete rerun; the unresolved intermittent behavior is tracked in [#342](https://github.com/alessio-locatelli/client-query-cache/issues/342). Existing Lychee missing-input warnings remain tracked in [#323](https://github.com/alessio-locatelli/client-query-cache/issues/323). Acquisition and existing-test timing logs have no failures or warnings.

The [hosted runtime validation](https://github.com/alessio-locatelli/client-query-cache/actions/runs/40374447408) at `588383c1` passes full coverage and strict-no-cover on CPython 3.14.0, 3.14.7 and 3.15. Subsequent edits affect documentation and planning artifacts only. Its parent-loss lifecycle test accepts a process already reaped between status checks while retaining the endpoint-removal assertion and shutdown deadline.

## Reproduce

Use the [baseline release wheel/environment commands](results.md#reproduce) for main and each frozen source named here, with isolated environments and identical locked dependencies. Use the collector from the candidate source for both installations. Follow the [registered cohort order](plan.md#rust-key-preparation-correction), using `--paths shared --repetitions 1` with the baseline populations/counts, and distinct output files per block/build. Verify installed package origins, especially under the normal environment-loading test command.

For separate sorted diagnostics add `--diagnostics` to the cold sorted command. For separate profiles use `--samples 256 --profile-dir "$REPORT_DIR/BUILD-profiles"`; aggregate every worker file for each model under its repetition subdirectory. Never use these instrumented durations in read-timing tables.

Run `PYTHONPATH=. "$BUILD_PYTHON" research/shared_find_misses/floors.py` from candidate source, adding `--candidate` for the candidate installation. Alternate five revision pairs. The script verifies example byte equality outside timing and prepares the corpus before its CPU interval.

For the final allocation correction, repeat only the sorted hot/cold commands at `5913ef1e`, with three alternating revision pairs and both models: 24 windows in total. Keep the preceding generic identity measurements attributed to `5bfff311`; do not pool the sources. The twelve additional identity controls use `--method identity --hot-keys 1024 --samples 8192 --workloads hot --models async --paths shared --repetitions 1 --document-bytes 4096`, with main first in odd pairs and candidate first in even pairs. Run separate identity-hot and sorted-hot profiles once per build using the same populations, async only, 256 calls per worker and distinct profile directories.

For the 279 existing tests, use the [native-trial test command](native-trials.md#reproduce-the-native-trials) with `and not native-key` appended to its selection. Before the balanced comparison, run that command once per environment with `--collect-only -n 0` to equalize plugin/test bytecode startup state. Then time three alternating revision pairs without those two collection flags. Keep the unbalanced acquisition separate. For phase attribution, run once per build with `--durations=0 --durations-min=0`; do not use those instrumented durations as acceptance timings. Retain selection counts and warning-free logs. New native/wire/limit cases are covered separately.
