# Telemetry training-policy comparison

Historical November 2026 measurements compared baseline `e76abce7` with
`0d1b757b02d722ec6a3d5af0dad4803ffc08d8ee`, using release PGO wheels,
CPython 3.14.7, PyMongo 4.19.0 and the same Fedora Toolbx host/lockfile.
The [native quality guide](../../docs/development/native-quality.md#release-build)
owns the shipping training mix. This report explains its selection, without
claiming a universal speedup from disabled telemetry.

## PGO training comparison

All three builds used Maturin PGO, Rust's locked release configuration, CPython 3.14.7, the same dependencies and local Linux wheel tags. Eight completed hot matrices used 50,000 reads per cell, CPU 0 affinity, one worker, eight keys and 4,096-byte documents. Order was baseline, 80/20 disabled, 50/50 disabled, 50/50 enabled, 80/20 enabled, 50/50 disabled, 80/20 disabled, baseline. The two baseline runs bracket the candidate runs; enabled candidate controls each ran once. All reports validated results and cache use and had no invalid reason.

Candidate changes relative to the corresponding baseline hot matrix:

| Model | Storage     | 80/20 throughput | 50/50 throughput | 80/20 CPU      | 50/50 CPU      |
| ----- | ----------- | ---------------- | ---------------- | -------------- | -------------- |
| sync  | independent | -1.3% to +0.6%   | -2.7% to +1.1%   | -0.6% to +1.2% | -1.1% to +2.8% |
| sync  | shared      | +0.2% to +0.8%   | -1.8% to -1.4%   | -0.7% to -0.1% | +1.4% to +1.8% |
| async | independent | +2.0% to +2.2%   | +0.9% to +2.4%   | -2.2% to -1.8% | -2.3% to -0.7% |
| async | shared      | -0.2% to +1.5%   | -1.3% to -1.0%   | -1.5% to +0.2% | +0.9% to +1.4% |

The 50/50 mix initially showed slower synchronous shared reads in both short runs. A longer 500,000-read shared pair did not confirm that result: 80/20 measured 68,799 reads/s and 7.193 CPU seconds; 50/50 measured 69,173 reads/s and 7.159 CPU seconds. Median latencies were 14.347 and 14.457 microseconds respectively. These mixed directions and the short-run spread do not establish a profile winner. The selected 80/20 mix prioritizes the ordinary disabled mode while retaining enabled training; no general speedup or regression-clearance claim is made.

A fresh 1,000-read cold matrix per build was also acquired. Cold results remain inconclusive: for example, the 80/20 asyncio independent cell used 22.3% more measured CPU and had 13.5% lower throughput than its baseline, with only a 1.0% median-latency increase. The 50/50 cell went in the opposite direction. There was insufficient execution budget for repeated cold pairs, so these observations cannot establish a repeatable release regression or improvement.

## Reproduce and limitations

Use the named source for historical comparisons, isolated installed wheels and
one collector. Build with Maturin PGO and locked release settings. Alternative
training uses `scripts/pgo_training.py --disabled-share 0.5`; selected default
is 0.8. Source `scripts/testcontainers-bridge.sh`, then run
`python -m benchmarks.public_shared_cache --samples 50000 --repetitions 1
--workers 1 --hot-keys 8 --models sync async --paths independent shared
--workloads hot --validate --disable-telemetry --output <new-path>` on CPU 0.
Use `--diagnostics` for enabled controls and 500,000 samples, sync/shared only,
for the longer pair. The unconditional-telemetry baseline requires the candidate
runner's constructor adapter from the [original procedure](https://github.com/alessio-locatelli/client-query-cache/blob/243cbfb790766e9ee25b3ecced1ffe83e96d083c/reports/opt-in-telemetry/summary.md#reproduction).

CPU/throughput include validation and coordination; enabled controls also inspect
observations. One worker/eight keys do not qualify pressure, aliases, other read
methods or contention. Cold results remain inconclusive. Raw outputs stay untracked.
