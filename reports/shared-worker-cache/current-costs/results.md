# Current shared-cache costs

This investigation addresses [#341](https://github.com/alessio-locatelli/client-query-cache/issues/341).
The [plan](plan.md) was committed before acquisition. The approved native find miss design is implemented. Matched release-build
measurements show lower cold sorted-read latency and reader CPU, with increased
memory and native publication cost. The user rejected those measured
tradeoffs; this report preserves that candidate as negative evidence while a
replacement is designed. It does not qualify the replacement.

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
key within the existing selection protocol. The implementation keeps exact
hash lookups and adds bounded compatible-limit directories, preserving owner
fallback when native publication is incomplete. The comparison below measures
this boundary; it does not qualify general capacity or replace the historical
promotion protocols.

## Matched implementation comparison

The same collector at candidate source
[`a04f47246c11e61b5094da7b3ad24591801c8fa3`](https://github.com/alessio-locatelli/client-query-cache/commit/a04f47246c11e61b5094da7b3ad24591801c8fa3)
ran installed clean main and candidate release wheels, with identical Python and
locked dependency sets. Main is the release revision above; the candidate native
SHA-256 is `e5a453c0c87b61b28ac08445753615de24392c100820306c77553b629a289667`.
Three revision pairs reverse order in the second pair and rotate the starting
API model. These 48 windows use the original populations and call counts.
Hot setup seeds only the warm catalogue, identically for both builds; the
initial controls seeded additional unread cold keys, so they are not matched
candidate comparisons.

All 48 windows have the expected hits/misses, zero bypasses and one stream.
Every hot read is local, with zero synchronous owner requests. Identity cold
reads also make no synchronous owner requests. Cold sorted reads make 1,024
selection requests per main window, versus 3–11 per candidate window. Native
selection deliberately retains owner fallback when a concurrent publication
cannot supply a validated snapshot or completeness is unavailable; removing
that fallback would weaken correctness.

Each cell below is the median [minimum, maximum] of three window statistics.
Worker and owner CPU are shown separately, in µs per completed read. The earlier
closed-loop, finish-barrier and memory limitations still apply.

### Sorted, cold: main and candidate

| API / build       |                     P50 µs |                     P95 µs |                     P99 µs |      Worker CPU µs/read |       Owner CPU µs/read |     MongoDB CPU µs/read |           Group PSS MiB |                    Reads/s |
| ----------------- | -------------------------: | -------------------------: | -------------------------: | ----------------------: | ----------------------: | ----------------------: | ----------------------: | -------------------------: |
| sync / main       |    805.10 [769.49, 851.50] | 3013.65 [1776.81, 3406.51] | 4591.28 [2197.62, 5369.12] | 574.75 [540.85, 608.65] | 195.31 [185.55, 205.08] | 181.41 [166.13, 193.37] | 243.61 [243.59, 243.63] | 3620.72 [3619.55, 4346.50] |
| sync / candidate  |    631.85 [625.89, 671.11] | 1903.29 [1279.68, 2225.84] | 2971.97 [2498.04, 3800.92] | 492.22 [455.15, 514.04] | 166.02 [156.25, 195.31] | 169.17 [167.46, 174.10] | 248.93 [248.04, 249.04] | 4675.59 [4428.46, 5227.20] |
| async / main      | 1035.93 [1030.05, 1147.51] | 3261.99 [2408.39, 3472.69] | 4342.47 [3519.77, 4632.99] | 828.04 [757.60, 837.19] | 224.61 [185.55, 234.38] | 198.16 [194.56, 208.55] | 245.06 [244.97, 245.08] | 3035.24 [2985.73, 3162.94] |
| async / candidate |    747.15 [738.98, 751.12] | 2614.40 [2234.44, 2767.84] | 3424.87 [3223.06, 3505.01] | 718.41 [681.15, 738.33] | 195.31 [185.55, 214.84] | 200.65 [194.96, 200.79] | 250.08 [249.84, 251.52] | 3992.83 [3889.71, 4124.35] |

### Sorted, hot: main and candidate

| API / build       |               P50 µs |                  P95 µs |                  P99 µs |     Worker CPU µs/read | Owner CPU µs/read | MongoDB CPU µs/read |           Group PSS MiB |                       Reads/s |
| ----------------- | -------------------: | ----------------------: | ----------------------: | ---------------------: | ----------------: | ------------------: | ----------------------: | ----------------------------: |
| sync / main       | 82.93 [72.74, 83.98] |  277.87 [88.10, 278.17] |  386.07 [99.28, 393.02] |  99.71 [67.31, 100.67] | 2.44 [0.00, 2.44] |   0.13 [0.10, 0.15] | 210.96 [210.92, 210.96] | 34529.13 [33934.97, 56615.52] |
| sync / candidate  | 71.99 [52.20, 72.55] | 181.16 [108.77, 315.82] | 314.04 [279.02, 398.92] |  77.01 [71.19, 106.13] | 2.44 [0.00, 4.88] |   0.25 [0.13, 4.58] | 216.02 [215.51, 216.16] | 42634.10 [36116.47, 50099.24] |
| async / main      | 51.04 [50.87, 78.88] | 351.77 [155.65, 368.97] | 387.50 [216.63, 389.57] | 102.16 [84.56, 104.47] | 2.44 [0.00, 2.44] |   1.38 [0.30, 4.19] | 212.41 [212.37, 212.49] | 37637.82 [36347.91, 41343.41] |
| async / candidate | 47.38 [47.07, 74.04] | 117.45 [112.89, 280.49] | 303.50 [190.37, 391.45] |   71.12 [69.17, 85.81] | 2.44 [0.00, 2.44] |   0.14 [0.12, 0.34] | 218.77 [217.75, 218.77] | 54367.04 [43458.70, 56053.22] |

### Identity, cold: main and candidate

| API / build       |                  P50 µs |                  P95 µs |                     P99 µs |      Worker CPU µs/read |    Owner CPU µs/read |  MongoDB CPU µs/read |           Group PSS MiB |                       Reads/s |
| ----------------- | ----------------------: | ----------------------: | -------------------------: | ----------------------: | -------------------: | -------------------: | ----------------------: | ----------------------------: |
| sync / main       | 247.64 [240.63, 276.14] | 712.21 [656.11, 737.92] |  1148.38 [932.74, 1307.85] | 202.00 [197.36, 210.98] | 48.83 [46.39, 51.27] | 64.52 [63.45, 70.55] | 237.14 [237.04, 237.15] | 13125.39 [11532.86, 13447.04] |
| sync / candidate  | 239.75 [231.71, 247.88] | 677.84 [396.67, 698.65] |  1146.34 [653.79, 1185.61] | 197.95 [169.23, 199.41] | 46.39 [39.06, 48.83] | 62.62 [53.06, 64.06] | 237.44 [237.28, 237.49] | 13342.35 [12934.72, 15725.81] |
| async / main      | 329.71 [324.52, 340.93] | 707.63 [567.21, 933.87] | 1100.54 [1047.26, 1445.28] | 298.58 [287.08, 327.16] | 46.39 [46.39, 48.83] | 60.10 [57.97, 65.36] | 238.50 [238.48, 238.67] |  10248.07 [9554.87, 11144.97] |
| async / candidate | 326.74 [318.57, 326.78] | 927.89 [752.86, 959.93] | 1549.77 [1335.70, 1645.04] | 313.16 [310.17, 326.87] | 51.27 [51.27, 53.71] | 61.76 [60.89, 67.31] | 238.78 [238.62, 238.81] |   9812.21 [9545.45, 10364.31] |

### Identity, hot: main and candidate

| API / build       |            P50 µs |               P95 µs |               P99 µs |  Worker CPU µs/read | Owner CPU µs/read | MongoDB CPU µs/read |           Group PSS MiB |                          Reads/s |
| ----------------- | ----------------: | -------------------: | -------------------: | ------------------: | ----------------: | ------------------: | ----------------------: | -------------------------------: |
| sync / main       | 7.44 [7.39, 7.60] | 27.09 [19.62, 31.23] | 34.49 [23.95, 35.07] | 10.14 [9.45, 10.77] | 0.61 [0.61, 1.22] |   0.03 [0.03, 0.19] | 213.01 [212.88, 213.18] | 339186.14 [295292.18, 398257.22] |
| sync / candidate  | 7.23 [4.66, 7.73] |   9.55 [7.37, 14.67] |  13.44 [8.92, 16.93] |   6.82 [5.27, 8.57] | 0.00 [0.00, 0.61] |   0.01 [0.01, 0.01] | 213.06 [213.02, 213.14] | 528231.85 [399395.01, 710215.05] |
| async / main      | 8.14 [5.80, 8.44] | 28.68 [17.77, 33.13] | 36.79 [22.73, 40.29] | 11.48 [8.23, 11.62] | 0.31 [0.31, 1.22] |   0.02 [0.02, 0.03] | 214.15 [214.06, 214.23] | 317969.79 [302857.84, 442958.65] |
| async / candidate | 8.50 [7.46, 8.54] | 21.30 [20.81, 22.91] | 29.72 [27.86, 30.94] | 11.02 [9.76, 11.62] | 0.61 [0.31, 0.92] |   0.03 [0.02, 0.03] | 214.50 [214.33, 214.72] | 324873.30 [299305.97, 385786.74] |

Cold sorted P50 decreases in all six pairs: 17.9–22.3% for sync and
27.1–34.9% for asyncio. Throughput increases 20.3–29.1% and 23.0–38.1%,
respectively. Summed worker/owner CPU decreases in all six pairs: 12.8–15.8%
for sync and 1.0–18.4% for asyncio. P95/P99 have mixed paired directions in
some comparisons; their overlapping ranges do not establish a universal tail
improvement. Hot sorted latency/CPU also varies substantially across windows.

Group PSS increases in every sorted pair, by 4.41–6.44 MiB (1.8–3.0%). Both
worker and owner contributions increase. These observations include live
mappings and allocator retention, not just directory bytes. Candidate find
admissions use the existing bounded native queues, while main find admissions
use the socket; writing queue pages increases physical residency. Directory
bookkeeping and changed allocation patterns also contribute, but this experiment
does not isolate their individual shares. Avoiding queue residency by sending
local admissions over the socket is a possible alternative with different CPU
and I/O costs, outside the measured candidate. The memory increase remains an
explicit acceptance tradeoff rather than a dismissed small regression.

Identity hot and cold median ranges mostly overlap. The first three asyncio
identity cold pairs all have higher candidate P99, while CPU and throughput
have mixed directions. A twelve-window control was registered, but not started before the user rejected
this candidate. The replacement requires a fresh matched comparison; these
identity-tail observations remain an unresolved limitation of the rejected
candidate and cannot be hidden by the sorted benefit.

### Native selection and maintenance floors

Five alternating batches per build use one family, 1/8/64 limits, 4 KiB payloads,
10,000 reads and 100 publication/removal cycles. Values are CPU ns per operation;
mutation includes payload allocation, publication and release. These are isolated
binding/native floors, not MongoDB read or write latency.

| Limits | Build     |           Exact |        Compatible | Absent capture | Publish/remove per entry |
| -----: | --------- | --------------: | ----------------: | -------------: | -----------------------: |
|      1 | main      | 759 [746, 1032] |                 — |              — |          977 [968, 1868] |
|      1 | candidate | 698 [685, 1199] | 1267 [1259, 1672] | 163 [158, 195] |        2142 [2104, 2240] |
|      8 | main      | 757 [751, 1290] |                 — |              — |          860 [856, 1578] |
|      8 | candidate |  690 [689, 714] | 1271 [1265, 1282] | 160 [159, 162] |        2050 [2012, 2129] |
|     64 | main      |  751 [736, 919] |                 — |              — |           827 [826, 832] |
|     64 | candidate |  691 [677, 714] | 1339 [1286, 1475] | 163 [156, 317] |        1974 [1958, 3210] |

Exact-hit medians do not regress. Directory maintenance does add work: candidate
publication/removal medians are about 2.0–2.4 times main (roughly 1.15–1.19 µs
more per entry). This is a reproducible regression and requires explicit
acceptance. The generic main operation does not maintain compatible-limit
directories; there is no equivalent main native compatible/miss-token floor.
The end-to-end comparison includes the owner work that these new operations
replace.

An exploratory version rebuilt directory storage on every change. Its candidate
mutation medians rose from 2.09 µs at one limit to 3.54 µs at 64 limits. Reusing
geometrically sized directory storage reduced the final 64-limit median to
1.97 µs. Retain this negative result: growth/shrink still rebuilds storage and
updates still write the family's limits; arbitrary family sizes have not been
qualified. The exploratory intermediate source was not frozen as a release
comparison and these numbers are not an independently reconstructable table.

### Separate transport diagnostics and correctness

Four instrumented cold sorted windows compare main/candidate in both API models.
Main makes 1,024 selection requests and 1,024 one-way admissions in each window;
candidate makes 7/8 selection requests (sync/async), 1,024 one-way admissions and
1,016 native-queue admissions. Worker bytes sent are 69,139,456 for main and
69,159,796/69,159,776 for candidate. Worker bytes received fall from 66,560 to
455/520. Eliminating selection exchanges does **not** eliminate result transport
or establish lower total request bytes: the local admission envelope is larger.
All endpoint timeout/failure/drop/recovery counters are zero.

Owner deltas show 1,024 admissions and 1,024 accepted results per window in both
builds, zero rejected measured admissions, and zero captures at observation.
Owner request deltas include one observer request; warmup admissions can also
cross the starting observation, so the worker deltas identify timed traffic.
The candidate warmup observations already contain 319/196 rejected duplicate
admissions (sync/async), versus 227/363 for main. These are expected competing
captures rejected by authoritative admission, not protocol failures. They are
retained without attributing the memory increase to duplicates: both builds
can make competing warmup captures. Owner CPU in the
timing tables includes background work completed during the read window and
can exclude admission work remaining after its finish barrier.

Small-capacity correctness cases in
[`test_shared_index_oracle.py`](../../../tests/shared_cache/test_shared_index_oracle.py)
exercise both unpublishable core entries and missing native directories, retain
owner compatible reuse, bound unpublished references by live core entries, and
reclaim entries/directories on removal and reset. Native operation tests and Loom
exercise directory mutation, payload reuse and validated snapshots. The Python
coverage gate reaches 100% with strict-no-cover; this does not claim 100% native
coverage, whose separate remaining work is tracked in
[#328](https://github.com/alessio-locatelli/client-query-cache/issues/328).

### Existing affected-test duration for the rejected candidate

The unchanged selection uses `test_adapter_paths.py`, `test_collection_reads.py`
and `test_sorted_find.py`, excluding names containing `native_find`,
`negative_find_limits`, `unportable_integer_find_keys`, `local_find_envelope` or
`negative-exact`. Each build runs the same current test source against an
isolated installed wheel and identical locked test/docs dependencies. All
selected runs execute 279 existing cases; newly added cases are validated
separately by the complete coverage gate. Import origins were checked under the
same environment-loading command.

Initial timing commands passed but emitted an uv warning because `--no-sync`
has no effect with `--no-project`. That redundant flag was removed and the three
alternating pairs repeated; only the warning-free replacement belongs in this timing summary. External
elapsed medians [ranges] are 71.49 [71.31, 71.78] seconds for main and
72.14 [71.62, 73.25] for candidate. Paired differences are +0.83, +1.76 and
−0.16 seconds. Overlapping ranges and mixed directions leave this uncertain;
it does not establish an accepted test-time regression.

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

For the matched implementation comparison, build main and candidate from clean
checkouts using the wheel/venv commands above with separate report directories.
Run the collector from candidate source for **both** installed environments,
checking `client_query_cache.__file__` resolves inside the selected environment.
Do not use an editable install or put `src/` on `PYTHONPATH`. For each of three
blocks, run the identity/sorted hot/cold commands above with `--paths shared
--repetitions 1`. Use main then candidate with `--models sync async` in blocks
one and three; candidate then main with `--models async sync` in block two.
Store distinct filenames per build/block. For the identity tail control, run
only `--method identity --hot-keys 1024 --samples 1024 --workloads cold --models
async --paths shared --repetitions 1` for six more alternating revision pairs.

Collect diagnostics separately with `--method find --hot-keys 128
--result-documents 16 --samples 256 --workloads cold --paths shared
--repetitions 1 --diagnostics`, once per installed build. Collect native floors
from candidate source with `PYTHONPATH=. "$BUILD_PYTHON"
research/shared_find_misses/floors.py --repetitions 1`, adding `--candidate`
only for candidate. Alternate revision order across five batches. Run no tests,
builds or other measurement campaign concurrently.

For existing-test timing, export the locked `test` and `docs` dependency groups
to two isolated environments, install the corresponding wheel, and run the same
candidate test source through each environment's Python. Use `/usr/bin/time`
around `uv run --no-project --env-file .env -- "$TEST_PYTHON" -m pytest -q
 tests/shared_cache/test_adapter_paths.py
 tests/shared_cache/test_collection_reads.py
 tests/shared_cache/test_sorted_find.py -k 'not native_find and not
 negative_find_limits and not unportable_integer_find_keys and not
 local_find_envelope and not negative-exact'`, using one shell command and normal
project environment loading (omit `--env-file .env` when absent). Use three
alternating main/candidate pairs, reversing order in the second. Preserve logs
and verify the selected test count and warning-free completion before comparing
external elapsed times.
