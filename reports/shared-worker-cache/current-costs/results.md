# Current shared-cache costs

This investigation addresses [#341](https://github.com/alessio-locatelli/client-query-cache/issues/341).
The [plan](plan.md) was recorded before acquisition. The current-release baseline
identifies duplicate query serialization and synchronous owner selection on cold
sorted finds. Two implemented native selection approaches were evaluated and withheld
from promotion; their complete evidence is in [native trials](native-trials.md).
The user subsequently directed moving measured slow work into Rust. The current
correction encodes shared find keys in Rust and reuses one query traversal;
its [current comparison](rust-encoding.md) retains the initial results and the
registered initialization correction. The native trials do not qualify it.

## Source and conditions

Measured on 2026-10-26 from clean release source
[`71dcbf790686b76dc97a72193a94ec63260af804`](https://github.com/alessio-locatelli/client-query-cache/commit/71dcbf790686b76dc97a72193a94ec63260af804),
using an installed 0.9.1 release wheel, CPython 3.14.7, PyMongo 4.18.2 and psutil
7.2.2 from `uv.lock`. Host: Intel Core i3-13100, eight logical CPUs, 64 GiB RAM,
Fedora 44 Toolbx, Linux 7.2.11, glibc 2.43. Rust: 1.99.1
(`58cf8f9c3`, 2026-10-13). The native binary SHA-256 is
`30f6fe3a11c12faffe6873dacf0a6a6e93645ff0747f7c457e5aa54febe80725`.
The pinned server is
`mongo:9.0.4@sha256:dc28ed5a9d0fc616903c3f463bb1e53b92b49f441721b91926e87d90bf957ce8`,
with two CPUs and 1 GiB memory. No builds or tests ran during timing.

The existing public harness ran four spawned workers with one in-flight read per
worker, majority concern and 4,096-byte document payloads. Identity reads warm
1,024 keys; sorted reads warm 128 groups of 16 documents. Hot windows contain
32,768 identity or 4,096 sorted reads; cold windows contain 4,096 identity or
1,024 sorted reads, selecting disjoint unwarmed keys. Each table cell is the
median **[minimum, maximum]** of three rotating-path windows. Requests are not
treated as independent repetitions or pooled to manufacture confidence bounds.

The shared configuration is the harness's 32 MiB cache budget, 40 MiB arena and
16,384 slots; independent caches use 64 MiB per worker. Both hot catalogues fit.
Cold sorted results exceed the shared budget and cause eviction while fitting
the independent budgets, so their smaller shared PSS is **not evidence of
equivalent-residency memory savings**.

Reader CPU sums workers and owner during measured reads, including background
work completed in that interval. MongoDB CPU is separate. Group PSS sums workers
and owner with live mappings, counting shared pages proportionally; it excludes
MongoDB and collector memory. These are closed-loop observations with different
completion durations. They do not measure fixed-demand total deployment CPU,
peak memory or all admission work after the finish barrier. Short hot intervals
particularly expose scheduling and CPU-counter resolution.

## Initial measurements

All 72 windows completed. Every hot cached call hit, every cold cached call
missed, and bypasses were zero. Independent windows had four streams; shared
windows had one. No acquisition or profiling failure/warning was observed.

### Identity, hot

| API / path          |                  P50 µs |                  P95 µs |                  P99 µs |      Reader CPU µs/read |  MongoDB CPU µs/read |           Group PSS MiB |                 Reads/s |
| ------------------- | ----------------------: | ----------------------: | ----------------------: | ----------------------: | -------------------: | ----------------------: | ----------------------: |
| sync / direct       | 169.39 [167.62, 171.18] | 224.48 [216.27, 233.39] | 355.60 [274.57, 367.49] | 114.80 [112.85, 115.30] | 44.92 [44.40, 46.11] | 163.03 [162.94, 163.11] |    22686 [22358, 23279] |
| sync / independent  |       8.16 [8.04, 8.31] |    28.68 [21.09, 41.71] |    63.52 [29.82, 79.77] |    12.43 [11.72, 14.55] |    0.01 [0.01, 0.30] | 180.92 [180.89, 180.94] | 276583 [252325, 305666] |
| sync / shared       |       5.18 [4.91, 7.02] |    25.11 [20.19, 27.79] |    32.17 [25.40, 32.24] |      9.57 [8.28, 10.47] |    0.02 [0.02, 0.36] | 213.46 [213.45, 213.49] | 400436 [373898, 446469] |
| async / direct      | 247.75 [246.53, 251.36] | 361.75 [334.78, 368.75] | 600.84 [576.74, 608.58] | 218.68 [216.71, 221.01] | 49.67 [49.00, 50.44] | 164.40 [164.39, 164.44] |    15236 [14965, 15434] |
| async / independent |       8.88 [8.84, 9.12] |    41.72 [36.81, 42.26] |    60.30 [51.76, 79.71] |    14.12 [14.07, 16.38] |    0.01 [0.01, 0.01] | 182.27 [182.25, 182.29] | 275599 [203906, 278531] |
| async / shared      |       5.60 [5.45, 8.28] |    26.89 [17.44, 33.18] |    34.26 [22.13, 37.81] |     10.97 [7.77, 12.81] |    0.02 [0.02, 0.07] | 214.56 [214.50, 214.78] | 345983 [287232, 488966] |

### Identity, cold

| API / path          |                  P50 µs |                   P95 µs |                     P99 µs |      Reader CPU µs/read |  MongoDB CPU µs/read |           Group PSS MiB |              Reads/s |
| ------------------- | ----------------------: | -----------------------: | -------------------------: | ----------------------: | -------------------: | ----------------------: | -------------------: |
| sync / direct       | 176.08 [170.74, 198.63] |  237.19 [232.80, 345.03] |    335.31 [331.72, 540.81] | 117.39 [115.50, 126.66] | 46.57 [45.14, 51.35] | 162.19 [162.19, 162.20] | 21982 [18290, 22411] |
| sync / independent  | 252.42 [243.01, 289.45] |  681.71 [593.29, 930.50] |  1343.34 [997.74, 1780.59] | 218.54 [207.22, 239.65] | 63.29 [57.65, 70.00] | 198.38 [198.38, 198.42] | 12739 [10593, 12890] |
| sync / shared       | 250.14 [242.46, 253.10] |  739.18 [683.23, 793.01] | 1168.55 [1157.77, 1213.24] | 248.72 [242.04, 251.29] | 65.22 [62.68, 68.77] | 237.75 [237.75, 237.82] | 13067 [12596, 13289] |
| async / direct      | 261.55 [249.88, 269.72] |  482.29 [385.69, 527.27] |    788.27 [721.70, 810.83] | 226.43 [221.53, 229.97] | 51.46 [49.97, 53.30] | 163.48 [163.46, 163.50] | 13699 [13209, 14843] |
| async / independent | 334.68 [328.61, 349.42] | 911.78 [580.51, 1129.33] |  1500.88 [868.82, 1595.38] | 339.83 [311.57, 353.09] | 58.87 [58.82, 64.74] | 199.82 [199.77, 199.85] |   9879 [9445, 10528] |
| async / shared      | 321.87 [321.78, 334.26] |  760.33 [690.18, 881.88] | 1433.26 [1015.43, 1785.43] | 356.38 [337.26, 364.23] | 60.81 [58.70, 63.48] | 238.94 [238.90, 238.95] |  10075 [9989, 10496] |

### Sorted, hot

| API / path          |                  P50 µs |                  P95 µs |                    P99 µs |      Reader CPU µs/read |     MongoDB CPU µs/read |           Group PSS MiB |              Reads/s |
| ------------------- | ----------------------: | ----------------------: | ------------------------: | ----------------------: | ----------------------: | ----------------------: | -------------------: |
| sync / direct       | 332.61 [318.14, 377.28] | 485.12 [408.75, 602.41] |   744.08 [551.38, 856.71] | 180.76 [172.68, 198.06] | 122.25 [118.70, 133.44] | 162.22 [162.20, 162.23] |  11312 [9679, 12162] |
| sync / independent  |    85.52 [84.76, 86.42] |  231.31 [91.14, 285.57] |    347.14 [97.33, 347.72] |   93.81 [76.51, 110.33] |       0.05 [0.02, 0.26] | 194.97 [194.96, 194.99] | 36106 [31460, 45152] |
| sync / shared       |    81.00 [46.22, 82.05] |   89.93 [81.61, 244.07] |    100.63 [88.34, 366.29] |    65.78 [57.50, 97.70] |       0.13 [0.11, 0.24] | 211.49 [211.49, 211.63] | 46396 [36023, 52807] |
| async / direct      | 406.85 [400.21, 428.61] | 744.36 [523.78, 809.38] | 1207.35 [710.18, 1325.05] | 299.69 [285.98, 299.86] | 130.10 [124.13, 131.24] | 163.54 [163.53, 163.59] |    8518 [8410, 9646] |
| async / independent |    75.05 [48.75, 85.45] | 200.09 [113.98, 297.96] |   281.23 [143.99, 428.76] |    88.51 [73.25, 89.76] |       0.03 [0.03, 0.03] | 196.26 [196.24, 196.28] | 38028 [37817, 46016] |
| async / shared      |    50.26 [47.22, 85.92] | 274.34 [268.33, 289.37] |   381.80 [378.31, 386.06] |    92.34 [89.32, 99.36] |       0.46 [0.41, 0.55] | 213.06 [213.04, 213.07] | 41763 [34999, 44225] |

### Sorted, cold

| API / path          |                  P50 µs |                     P95 µs |                     P99 µs |       Reader CPU µs/read |     MongoDB CPU µs/read |           Group PSS MiB |              Reads/s |
| ------------------- | ----------------------: | -------------------------: | -------------------------: | -----------------------: | ----------------------: | ----------------------: | -------------------: |
| sync / direct       | 330.21 [320.18, 332.41] |    443.34 [397.41, 638.62] |    577.37 [568.10, 971.88] |  176.59 [167.14, 182.92] | 127.61 [123.67, 130.62] | 162.03 [162.01, 162.04] | 11550 [10596, 11950] |
| sync / independent  | 564.14 [550.67, 641.60] | 1801.77 [1732.25, 2012.10] | 2694.56 [2598.65, 2986.95] |  495.25 [478.44, 574.11] | 182.18 [176.51, 211.42] | 261.68 [261.63, 261.74] |    5308 [4541, 5463] |
| sync / shared       | 789.30 [783.47, 798.53] | 2562.60 [1098.75, 2576.52] | 3144.84 [1348.31, 3277.20] |  807.68 [634.61, 835.25] | 194.93 [153.16, 203.81] | 244.31 [244.25, 244.37] |    3812 [3733, 4785] |
| async / direct      | 399.00 [398.02, 432.10] |    525.35 [486.58, 856.37] |   707.63 [575.43, 1297.91] |  280.50 [280.01, 305.63] | 130.38 [129.21, 141.49] | 163.35 [163.29, 163.36] |    9626 [7939, 9759] |
| async / independent | 646.30 [635.51, 651.72] |  1746.56 [949.72, 2196.82] | 2679.59 [1847.88, 2875.91] |  563.96 [526.67, 666.00] | 160.19 [148.84, 198.06] | 263.04 [263.04, 263.06] |    5084 [4485, 5744] |
| async / shared      | 928.74 [899.88, 991.99] | 2768.92 [2765.99, 3008.48] | 3972.05 [3620.14, 4436.46] | 995.50 [954.24, 1016.50] | 199.65 [185.41, 201.61] | 245.71 [245.65, 245.75] |    3321 [3232, 3542] |

Cold sorted median ranges do not overlap between independent and shared paths
in either model. Their reader CPU ranges are also separated, establishing a
repeatable current cost for this workload, without claiming a regression from
an earlier release. Hot sorted ranges overlap and do not establish a reliable
shared-versus-independent ranking. Shared identity hits have lower median
latency and CPU in these windows, but the owner raises small-catalogue memory.

## Attribution and alternatives

Sixteen separate cProfile windows used 256 calls per worker, both models,
hot/cold and independent/shared paths. All four worker profiles per window were
inspected. Instrumented durations are excluded from the timing tables.

For each 1,024-call shared cold sorted window, `_local_find` and `_find_message`
each execute 1,024 times. Together their key encodings traverse `to_wire` 67,584
times. Source inspection confirms that the discriminator used for local lookup
and the family sent to the owner both include the query. The sync profile shows
1,024 selection requests; asyncio's request function has 2,048 resumptions,
which must not be mistaken for twice as many RPCs. Both paths encode 2,048
frames: selection and admission. Shared identity cold profiles have 1,024
admission frames and no selection requests. Hot sorted profiles have no
selection request or frame encoding.

`CursorCapture.append` runs 16,384 times per sorted cold window in both cached
paths, preserving document snapshots. Hot profiles show cursor argument
binding, query classification/canonicalization and BSON decoding in both paths.
These observations distinguish application/result work from the additional
shared selection/key preparation; profiler times are not CPU savings estimates.

Direct reads and independent ownership are concrete alternatives in the tables.
Direct reads avoid admission and are fastest for this all-cold case. Independent
caches avoid the shared control exchange, retain more cold data under the
configured budgets, and duplicate hot storage and streams. Shared local hits
avoid repeated MongoDB reads but do not amortize the owner's memory for either
small hot catalogue measured here.

The user selected native family lookup/local capture over reusing a prepared
key within the existing selection protocol. The [native trials](native-trials.md) retain both candidates and their negative
results. Neither is accepted; no full historical protocol requalification is
claimed.

## Reproduce

Use this report's source revision for the initial acquisition. Follow
[contributor setup](../../../CONTRIBUTING.md), then choose a fresh untracked
`REPORT_DIR`. The commands collect new measurements; committed summaries do not
retain individual samples or independently recover the original tables.
`--compatibility linux` builds a local measurement wheel, not a distribution
artifact for other hosts.

```bash
set -euo pipefail
mkdir -p "$REPORT_DIR/wheels"
uv run -- maturin build --release --locked --compatibility linux --out "$REPORT_DIR/wheels"
uv export --frozen --only-group benchmark --no-emit-project --no-hashes --output-file "$REPORT_DIR/requirements.txt"
uv venv --python .venv/bin/python "$REPORT_DIR/venv"
uv pip install --python "$REPORT_DIR/venv/bin/python" --requirements "$REPORT_DIR/requirements.txt" "$REPORT_DIR"/wheels/*.whl
source scripts/testcontainers-bridge.sh

for workload in hot cold; do
    if [[ "$workload" == hot ]]; then
        identity_samples=8192
        sorted_samples=1024
    else
        identity_samples=1024
        sorted_samples=256
    fi
    "$REPORT_DIR/venv/bin/python" -m benchmarks.public_shared_cache \
        --method identity --hot-keys 1024 --samples "$identity_samples" \
        --repetitions 3 --document-bytes 4096 --workloads "$workload" \
        --output "$REPORT_DIR/identity-$workload.json"
    "$REPORT_DIR/venv/bin/python" -m benchmarks.public_shared_cache \
        --method find --hot-keys 128 --result-documents 16 \
        --samples "$sorted_samples" --repetitions 3 --document-bytes 4096 \
        --workloads "$workload" --output "$REPORT_DIR/sorted-$workload.json"
done
```

For separate profiling, run each method with `--samples 256 --repetitions 1
--paths independent shared --profile-dir "$REPORT_DIR/profiles/METHOD"`, leaving
both models and workloads enabled and keeping distinct method directories.
Aggregate all four `MODEL-WORKLOAD-PATH-WORKER.pstats` files per window with
`pstats.Stats`; inspect exclusive times and call paths without summing overlapping
cumulative times. For each raw window, divide `measured_cpu_seconds` and
`server_cpu_seconds` by four times `samples_per_worker`; group memory is
`worker_pss_bytes + owner_pss_bytes`. Do not treat stream counts as wire-byte
measurements or worker profiles as owner CPU attribution.
