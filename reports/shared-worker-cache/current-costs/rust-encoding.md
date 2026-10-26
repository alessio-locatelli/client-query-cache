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

## Validation boundary

The Python coverage gate reaches 100% with strict-no-cover. Native wire-byte, specialized scalar, stack-guard, budget and cursor cases are exercised; this does not claim complete native coverage ([#328](https://github.com/alessio-locatelli/client-query-cache/issues/328)). One earlier full-suite TCP recovery timeout passed in isolation and on the complete rerun; the unresolved intermittent behavior is tracked in [#342](https://github.com/alessio-locatelli/client-query-cache/issues/342). Existing Lychee missing-input warnings remain tracked in [#323](https://github.com/alessio-locatelli/client-query-cache/issues/323). Acquisition and existing-test timing logs have no failures or warnings.

## Reproduce

Use the [baseline release wheel/environment commands](results.md#reproduce) for main and each frozen source named here, with isolated environments and identical locked dependencies. Use the collector from the candidate source for both installations. Follow the [registered cohort order](plan.md#rust-key-preparation-correction), using `--paths shared --repetitions 1` with the baseline populations/counts, and distinct output files per block/build. Verify installed package origins, especially under the normal environment-loading test command.

For separate sorted diagnostics add `--diagnostics` to the cold sorted command. For separate profiles use `--samples 256 --profile-dir "$REPORT_DIR/BUILD-profiles"`; aggregate every worker file for each model under its repetition subdirectory. Never use these instrumented durations in read-timing tables.

Run `PYTHONPATH=. "$BUILD_PYTHON" research/shared_find_misses/floors.py` from candidate source, adding `--candidate` for the candidate installation. Alternate five revision pairs. The script verifies example byte equality outside timing and prepares the corpus before its CPU interval. For the 279 existing tests, use the [native-trial test command](native-trials.md#reproduce-the-native-trials) with `and not native-key` appended to its selection; use three alternating revision pairs and retain warning-free logs. New native/wire/limit cases are covered separately.
