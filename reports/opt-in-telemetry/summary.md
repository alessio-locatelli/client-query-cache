# Bounded telemetry measurements

Baseline: `e76abce7` (`main`). Final candidate implementation: `0d1b757b02d722ec6a3d5af0dad4803ffc08d8ee`. The unprofiled candidate was an earlier uncommitted build of this implementation. Both used release wheels, the same lockfile, Python 3.14.7, PyMongo 4.19.0 and the Fedora Toolbx host. Builds and environment preparation were outside the execution budget. The first comparison used wheels without PGO.

The accepted matrix ran two pairs in AB/BA order with 1,000 reads per worker, one worker, eight hot keys and 4,096-byte documents. Each pair covered hot/cold identity reads, independent/shared storage and sync/async execution. Both sides used `--validate`. The baseline collected diagnostics; the candidate ran with telemetry disabled via `--disable-telemetry`. Constructor propagation and absent candidate cache observations confirmed the timed policy. Result checks, MongoDB command deltas and cold follow-up hits verified equivalent outcomes without candidate snapshots.

## Unprofiled paired results

Each cell gives the minimum and maximum candidate change across the two pairs. Negative latency/CPU and positive throughput are favorable. These short runs do not establish a general performance improvement.

| Model | Storage     | Workload | Median latency change | Throughput change | Process CPU change |
| ----- | ----------- | -------- | --------------------- | ----------------- | ------------------ |
| sync  | independent | hot      | +3.3% to +51.8%       | -21.5% to -12.1%  | +13.1% to +27.5%   |
| sync  | shared      | hot      | -39.0% to +59.0%      | -7.5% to +14.7%   | -11.9% to +6.5%    |
| sync  | independent | cold     | -11.3% to +9.0%       | -15.1% to +8.6%   | -7.3% to +20.5%    |
| sync  | shared      | cold     | -9.6% to +0.1%        | -1.0% to +2.5%    | -6.0% to -2.8%     |
| async | independent | hot      | -0.5% to +0.9%        | +5.7% to +6.1%    | -4.9% to -4.9%     |
| async | shared      | hot      | -3.8% to -2.2%        | +10.1% to +18.6%  | -14.5% to -8.7%    |
| async | independent | cold     | -13.6% to +12.0%      | -5.8% to +19.7%   | -14.6% to +5.1%    |
| async | shared      | cold     | +0.5% to +1.0%        | -2.3% to -0.7%    | -6.4% to +0.5%     |

The synchronous independent hot cell initially appeared slower. A 50,000-read matched pair, with both processes and their children pinned to CPU 0, did not reproduce that slowdown:

| Measurement           | Baseline | Disabled candidate |
| --------------------- | -------- | ------------------ |
| Median latency (us)   | 14.398   | 14.217             |
| p95 latency (us)      | 15.309   | 15.749             |
| Reads/second          | 61463.3  | 61462.3            |
| Process CPU (seconds) | 0.805173 | 0.805842           |

Throughput was effectively unchanged and CPU differed by 0.08%. This investigation, the sign reversals in several matrix cells and the enabled control show substantial short-run variation. Small cold-read differences remain inconclusive. No broad regression-clearance or speedup claim follows from these measurements.

## Reproduction

Use isolated release environments for each checkout (`uv sync --no-editable` with a separate `UV_PROJECT_ENVIRONMENT`). Source the repository's `scripts/testcontainers-bridge.sh` in Toolbx. The runner creates a disposable replica set; no production deployment is involved.

Use the candidate runner in both checkouts. The baseline adapter must omit `enable_telemetry` constructor keywords and the two `manager.enable_telemetry` early-return probes, since baseline collection is unconditional. Its validated execution and workload remain identical. The adapter was confined to the disposable baseline worktree.

```sh
python -m benchmarks.public_shared_cache \
  --output /tmp/agents/telemetry-run.json \
  --samples 1000 --repetitions 1 --workers 1 --hot-keys 8 \
  --models sync async --paths independent shared --workloads hot cold \
  --validate MODE
```

Replace `MODE` with `--diagnostics` for the baseline and enabled control, or `--disable-telemetry` for the disabled candidate. Run baseline/candidate, then candidate/baseline, with otherwise matched settings. The focused investigation used `taskset -c 0`, `--samples 50000 --models sync --paths independent --workloads hot` and the same validation modes.

## Limits and rejected runs

- A preceding 80-read pilot pair was too noisy for conclusions. An earlier candidate attempt failed on the shared facade's missing `max_entries` capability; that defect was fixed before the accepted pairs. The incomplete pair is excluded.
- An unpinned 50,000-read baseline attempt completed its cell but exceeded its 11-second process limit during shutdown. It is excluded; the accepted pinned pair completed normally with 17-second process limits.
- One enabled candidate matrix provides a control, not another repeated pair.
- After the unprofiled build, review and integration testing refined disabled diagnostic errors, the advanced shared facade, owner activation timestamp reuse and equivalent counter guards. These changes affect diagnostics, setup, recovery or enabled accounting; they do not change the warmed disabled identity-read loop. They were functionally validated and included in the separate PGO comparison below; the unprofiled experiment was not repeated. The measured native extension SHA-256 was `ba26d51fe882bf47859f803dc058481affaaeee42eeb1c199c6531f53731757c` (baseline: `f4906daaccf328ddac706052899816c024fdd4a3c886fdf8a45b5ca7ac76e6a1`).
- Process CPU and throughput include runner coordination and per-result validation after each individual latency sample. Enabled runs also perform explicit observation checks; these are not pure library-operation CPU estimates.
- The matrix covers only one worker and a small identity catalogue. Retention pressure, aliases, other read methods, sustained invalidation, large queues and multiprocess contention were not timed. Functional tests and the producer audit cover behavior, not performance equivalence for those paths.
- The original batch used roughly 317 seconds including launcher execution, warmup, rejected attempts and container cleanup, exceeding its five-minute allowance by about 17 seconds. The earlier 294-second estimate omitted post-report cleanup for the first two untimed runs and cleanup after the timed-out baseline. Artifact and container lifecycle timestamps correct those omissions; subsequent process durations were recorded with `/usr/bin/time`. The user accepted this recorded cleanup overrun as an exception; no further execution is planned under this allowance.
- A baseline-only 32-test inspection timing of 4.33 seconds and subsequent test runs belong to the separately authorized validation tier, rather than either standalone comparison allowance.
- Raw JSON and logs remain disposable, untracked files under `/tmp/agents/`; only this summary is retained.

## PGO training comparison

Release builds train cache-core workloads in both modes. The selected mix gives 80% of each cache-core workload's timed allocation to disabled telemetry and 20% to enabled telemetry. The comparison also tested a 50/50 mix. Each mix preserves the workload's total timed allocation, including the existing shorter allocation for limited-admission workloads. Setup and enabled verification passes run in addition to those timed allocations; the weights do not claim exact instruction-count proportions. Primitive index, key, capture and echo workloads retain their own defaults or intrinsic instrumentation; the mix controls `CacheCoreConfig` policy, not every low-level binding independently.

All three builds used Maturin PGO, Rust's locked release configuration, CPython 3.14.7, the same dependencies and local Linux wheel tags. Eight completed hot matrices used 50,000 reads per cell, CPU 0 affinity, one worker, eight keys and 4,096-byte documents. Order was baseline, 80/20 disabled, 50/50 disabled, 50/50 enabled, 80/20 enabled, 50/50 disabled, 80/20 disabled, baseline. The two baseline runs bracket the candidate runs; enabled candidate controls each ran once. All reports validated results and cache use and had no invalid reason.

Candidate changes relative to the corresponding baseline hot matrix:

| Model | Storage     | 80/20 throughput | 50/50 throughput | 80/20 CPU      | 50/50 CPU      |
| ----- | ----------- | ---------------- | ---------------- | -------------- | -------------- |
| sync  | independent | -1.3% to +0.6%   | -2.7% to +1.1%   | -0.6% to +1.2% | -1.1% to +2.8% |
| sync  | shared      | +0.2% to +0.8%   | -1.8% to -1.4%   | -0.7% to -0.1% | +1.4% to +1.8% |
| async | independent | +2.0% to +2.2%   | +0.9% to +2.4%   | -2.2% to -1.8% | -2.3% to -0.7% |
| async | shared      | -0.2% to +1.5%   | -1.3% to -1.0%   | -1.5% to +0.2% | +0.9% to +1.4% |

The 50/50 mix initially showed slower synchronous shared reads in both short runs. A longer 500,000-read shared pair did not confirm that result: 80/20 measured 68,799 reads/s and 7.193 CPU seconds; 50/50 measured 69,173 reads/s and 7.159 CPU seconds. Median latencies were 14.347 and 14.457 microseconds respectively. These mixed directions and the short-run spread do not establish a profile winner. The selected 80/20 mix prioritizes the ordinary disabled mode while retaining enabled training; no general speedup or regression-clearance claim is made.

A fresh 1,000-read cold matrix per build was also validated after resuming. Cold results remain inconclusive: for example, the 80/20 asyncio independent cell used 22.3% more measured CPU and had 13.5% lower throughput than its baseline, with only a 1.0% median-latency increase. The 50/50 cell went in the opposite direction. There was insufficient execution budget for repeated cold pairs, so these observations cannot establish a repeatable release regression or improvement.

The additional PGO execution allowance stayed below five minutes, with a conservative bound of about 293 seconds. The wrappers recorded 155.32 seconds before pausing and 118.61 after resuming, but the interrupted child continued cleanup after its wrapper stopped. Container lifecycle timestamps extend the first batch through the last cleanup event; rounding that timestamp upward and allowing two further seconds for process exit gives the 293-second bound. The interrupted 80/20 cold attempt lacks a completed process result and is excluded. Completed pre-pause hot runs are retained; the cold matrices were rerun together after resuming. The resumed batch stopped before another long shared pair, and the corrected cumulative budget leaves too little time for further measurements. No test or build ran during either comparison batch.

Measured extension SHA-256 values:

- baseline: `0fd15005b7f30ba115e92ac07266591f892915ec78cd4207d839cc23612f7c9e`.
- 80/20: `b796c0a27dc3ac4b73c86598eb9e769ed3d18cf1e5d4d4cab399de465259b686`.
- 50/50: `a7a57cc4d2abef25f1b2b70da8284e87cf3706255f5bc1a57f95c2284aba600f`.

To reproduce, build each checkout with its locked release configuration and `maturin build --release --pgo --locked --compatibility linux --interpreter <python-3.14>`. Use isolated output directories and installed-wheel environments. The local Linux tag avoids imposing portable-wheel compliance on the Fedora host; published release builds retain their normal Zig/manylinux configuration. For the alternative mix, set the temporary checkout's Maturin `pgo-command` to `python scripts/pgo_training.py --disabled-share 0.5`; the selected default is 0.8. Use the runner command above with `taskset -c 0`, `--samples 50000 --workloads hot`, both models and both storage paths. Use `--diagnostics` for enabled runs and `--disable-telemetry` for disabled runs. The longer pair uses `--samples 500000 --models sync --paths shared --workloads hot`; cold matrices use `--samples 1000 --workloads cold`.

## Test execution comparison

The separate validation tier timed the 32 existing inspection cases against installed PGO wheels, using the same pytest options and dependencies. Order was baseline/candidate, candidate/baseline, then baseline/candidate. Raw wall times include interpreter and pytest startup:

| Run | Baseline | Candidate |
| --- | -------- | --------- |
| 1   | 2.14 s   | 4.40 s    |
| 2   | 2.01 s   | 1.93 s    |
| 3   | 2.03 s   | 2.08 s    |

The first candidate run took 1.40 seconds inside pytest; subsequent candidate runs took 0.39–0.42 seconds and baseline runs took 0.38–0.39 seconds. The follow-up pair did not reproduce the first-run delay. These small startup-dominated runs support no general test-speed claim. The 49 newly added telemetry cases ran separately in 1.93 seconds wall time, with 0.41 seconds reported inside pytest; they are not included in the existing-case comparison.

Reproduce existing-case timings with `/usr/bin/time -f %e <wheel-env>/bin/python -m pytest -n 0 -q tests/core/test_inspection.py` from each checkout. Run `tests/core/test_telemetry.py` separately in the candidate environment for the new cases.
