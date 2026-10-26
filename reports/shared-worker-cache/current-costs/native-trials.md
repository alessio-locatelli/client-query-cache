# Native find trials

These implementation trials belong to [issue #341](https://github.com/alessio-locatelli/client-query-cache/issues/341). The [current-cost results](results.md) contain the initial release baseline and interpretation limits. Neither native candidate is accepted for promotion.

## Matched implementation comparison

The same collector at candidate source
[`a04f47246c11e61b5094da7b3ad24591801c8fa3`](https://github.com/alessio-locatelli/client-query-cache/commit/a04f47246c11e61b5094da7b3ad24591801c8fa3)
ran installed clean main and candidate release wheels, with identical Python and
locked dependency sets. Main is the [release baseline](results.md#source-and-conditions); the candidate native
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
Worker and owner CPU are shown separately, in µs per completed read. The [baseline measurement limits](results.md#source-and-conditions), including
closed-loop duration, the finish barrier and memory scope, still apply.

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
[`test_shared_index_oracle.py` at the directory candidate](https://github.com/alessio-locatelli/client-query-cache/blob/a04f47246c11e61b5094da7b3ad24591801c8fa3/tests/shared_cache/test_shared_index_oracle.py)
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

## Approved filter replacement

The user rejected the directory candidate's resource costs and approved the
replacement design before implementation. Its clean release source is
[`4d6aa936c8e29a5164e7601de3ec886aad5e8b16`](https://github.com/alessio-locatelli/client-query-cache/commit/4d6aa936c8e29a5164e7601de3ec886aad5e8b16);
the native SHA-256 is `29e76bd3c6fd5d2d89f6b1894eafef8288c3b234b4822ebe286cc45043f5fa92`.
Installed Python and locked benchmark dependency versions match main. Exact
find hits remain native. A bounded counting family filter authorizes definite
misses; possible family membership retains owner compatible-limit selection.
Find admissions use the existing socket transport. The allocator reuses its
free-list word while a payload is live, avoiding a larger allocation record or
per-family maps. The filter itself adds one atomic word per configured native
slot (128 KiB at the measured 16,384 slots).

### Replacement native floors and saturation

Five alternating main/replacement batches use the same diagnostic and conditions
as the earlier floors. Compatible lookup now returns owner fallback, so its
column measures that decision rather than copying a compatible result.
All values are CPU ns per operation, median [minimum, maximum].

| Limits | Build       |          Exact | Compatible fallback | Absent capture | Publish/remove per entry |
| -----: | ----------- | -------------: | ------------------: | -------------: | -----------------------: |
|      1 | main        | 755 [748, 773] |                   — |              — |           975 [972, 988] |
|      1 | replacement | 671 [668, 688] |      248 [245, 288] | 137 [134, 141] |          928 [921, 1356] |
|      8 | main        | 756 [750, 760] |                   — |              — |           854 [850, 863] |
|      8 | replacement | 673 [669, 709] |      244 [243, 255] | 135 [131, 136] |           805 [802, 830] |
|     64 | main        | 752 [745, 766] |                   — |              — |          827 [821, 1230] |
|     64 | replacement | 687 [669, 739] |      245 [242, 252] | 134 [134, 182] |           777 [773, 813] |

Publication/removal medians are 4.9–6.1% lower than main; exact-hit medians are
8.7–11.2% lower. The one-limit replacement mutation batch has one high outlier,
retained in the range; four of five pairs are lower, so it does not establish a
repeatable regression. Removing directory allocations and membership maps,
reusing allocator metadata and sharing the family's hash computation remove
the rejected maintenance cost. These isolated floors do not imply equivalent
end-to-end percentages.

A separate fixed-capacity diagnostic uses 4,096 slots, one-byte payloads and
4,096 absent-family probes per load level. Every resident exact result is
validated; every resident family requiring a different limit falls back rather
than authorizing local capture. Releasing every payload restores definite
absence for all original families, with zero published entries.

| Resident families | Absent-family owner fallbacks | False-positive rate |
| ----------------: | ----------------------------: | ------------------: |
|                 1 |                      0 / 4096 |               0.00% |
|               128 |                     18 / 4096 |               0.44% |
|               512 |                    214 / 4096 |               5.22% |
|              2048 |                   1707 / 4096 |              41.67% |

The high-load result is a retained limitation: the filter does not promise to
eliminate every miss-selection request at capacity. Collisions cost owner
selection, while exact hits and authoritative compatible reuse remain intact.

The preliminary 48-window comparison at `4d6aa936` completed with expected
cache outcomes. Sorted cold P50 medians fell from 821 to 654 µs (sync) and
949 to 786 µs (async); group PSS fell in every sorted pair, by 0.13–1.80 MiB.
This removed the rejected directory candidate's measured memory increase.
However, hot measurements remained noisy. Async sorted P50 was 48.46
[47.15, 54.86] µs for main versus 84.02 [48.61, 84.39] for the replacement;
sync identity hot P50 was 6.44 [5.22, 7.34] versus 7.58 [6.03, 7.62]. These
ranges overlap, so neither apparent slowdown is established by this batch.
Sync identity cold P99 did have separated ranges: 975 [882, 1117] versus
1151 [1128, 1504] µs. That finding needs investigation rather than acceptance.

Preliminary existing-test elapsed medians [ranges] were 70.68 [70.56, 71.24]
seconds for main and 71.78 [71.12, 72.00] for the replacement. Native queues
were unused for measured find admissions, and no acquisition/test warning or
failure was observed. These preliminary results do not qualify the final build.

Inspection also found avoidable locked atomic increments in owner-exclusive
filter updates. The final refinement uses atomic loads/release stores under
exclusive writer access. The registered final comparison repeats all 48
windows, native floors and existing-test pairs, adding a generic native identity
lookup diagnostic to investigate the tail finding without MongoDB.

A separate verbose link-check audit reproduces existing missing-input warnings
for files that exist, tracked in
[#323](https://github.com/alessio-locatelli/client-query-cache/issues/323).
They are outside this runtime change; successful benchmark acquisitions and
runtime tests do not erase that development-tool warning.

## Final release comparison

The final clean source is
[`a403bc50eed94a99566d91b0f14340b4803027f3`](https://github.com/alessio-locatelli/client-query-cache/commit/a403bc50eed94a99566d91b0f14340b4803027f3);
the native SHA-256 is `abb4acc8501b840e126befd08b0c133fbcf7ab5db9184e5440552a27483fb074`.
It contains the owner-exclusive counter stores, socket-only find admission and
reused namespace membership sets. Both installed environments use the same
CPython and locked dependencies; installed import origins were checked for
benchmarking and the environment-loading test command. No build or test runs
alongside workload timing.

### Final native floors

The same diagnostic runs five alternating batches per build. Values are CPU ns
per operation, median [minimum, maximum].

| Limits | Build |          Exact | Compatible fallback | Absent capture | Publish/remove per entry |
| -----: | ----- | -------------: | ------------------: | -------------: | -----------------------: |
|      1 | main  | 773 [752, 791] |                   — |              — |           983 [977, 995] |
|      1 | final | 675 [669, 766] |      241 [238, 290] | 133 [132, 136] |           924 [919, 991] |
|      8 | main  | 753 [753, 763] |                   — |              — |           851 [848, 869] |
|      8 | final | 681 [675, 789] |      256 [239, 293] | 136 [133, 178] |          811 [811, 1519] |
|     64 | main  | 757 [751, 765] |                   — |              — |          831 [819, 1296] |
|     64 | final | 679 [674, 938] |      247 [239, 289] | 135 [133, 137] |           789 [787, 844] |

All three final exact and publication/removal medians are below main. Retained
outliers cross the main range in some cases; these small native batches do not
prove an improvement in every invocation. The absent-capture column uses a
short sentinel family, in both preliminary and final diagnostics; it is a
lower bound and does not represent hashing a full MongoDB query family.
The fixed-capacity saturation counts are unchanged from the preceding table.

An identical generic identity lookup was also measured in each native batch.
Main: 300.4 [298.1, 300.8] ns.
Final: 303.7 [300.7, 306.8] ns.
A preceding five-batch check of the same native binary had the opposite median
direction (main 304.0 ns, candidate 301.9 ns). The few-nanosecond differences do
not establish a repeatable generic lookup slowdown or explain millisecond
MongoDB-read tails. The workload comparison must assess those tails separately.

### Final workload comparison

All 48 final windows have expected hits/misses, zero bypasses and one stream.
All hot reads are local with zero owner requests. Cold identity windows have
zero owner requests. Every cold sorted main window makes 1,024 selection
requests; every final candidate window makes four. These remaining requests
are retained, not described as zero selection traffic. The following cells
summarize three windows per build with their full ranges.

#### Sorted, cold

| API / build   |                   P50 µs |                     P95 µs |                     P99 µs |      Worker CPU µs/read |       Owner CPU µs/read |     MongoDB CPU µs/read |           Group PSS MiB |                    Reads/s |
| ------------- | -----------------------: | -------------------------: | -------------------------: | ----------------------: | ----------------------: | ----------------------: | ----------------------: | -------------------------: |
| sync / main   |  853.46 [811.59, 900.31] | 2414.87 [2199.43, 2567.48] | 3343.03 [2792.91, 3516.14] | 595.85 [594.15, 610.49] | 205.08 [195.31, 214.84] | 195.13 [187.51, 195.89] | 243.49 [243.45, 243.50] | 3709.42 [3668.90, 3916.12] |
| sync / final  |  638.56 [621.69, 648.30] | 2022.03 [1967.47, 2110.54] | 2676.41 [2662.89, 2700.56] | 536.25 [530.52, 545.71] | 175.78 [166.02, 175.78] | 198.13 [191.41, 217.20] | 241.77 [241.34, 241.80] | 4808.24 [4715.03, 4970.93] |
| async / main  | 970.00 [944.63, 1016.44] | 2310.48 [1849.87, 2859.76] | 5166.92 [3628.45, 7334.38] | 784.42 [748.46, 785.21] | 205.08 [205.08, 205.08] | 191.60 [178.91, 196.11] | 244.91 [244.89, 245.00] | 3344.44 [3276.58, 3369.42] |
| async / final |  744.75 [743.43, 746.95] | 2297.09 [2233.23, 2485.66] | 3275.57 [3100.08, 5275.90] | 704.56 [674.09, 709.25] | 185.55 [175.78, 185.55] | 196.92 [190.89, 201.63] | 243.17 [243.15, 243.17] | 4196.41 [4147.55, 4208.39] |

#### Sorted, hot

| API / build   |               P50 µs |                  P95 µs |                  P99 µs |    Worker CPU µs/read | Owner CPU µs/read | MongoDB CPU µs/read |           Group PSS MiB |                       Reads/s |
| ------------- | -------------------: | ----------------------: | ----------------------: | --------------------: | ----------------: | ------------------: | ----------------------: | ----------------------------: |
| sync / main   | 57.20 [48.00, 84.29] | 233.66 [153.55, 316.47] | 333.90 [202.02, 396.29] | 80.31 [71.76, 110.88] | 2.44 [0.00, 2.44] |   0.12 [0.12, 0.19] | 210.87 [210.79, 210.89] | 47727.36 [30471.88, 50726.40] |
| sync / final  | 47.56 [44.73, 53.41] | 219.90 [159.74, 246.51] | 287.18 [223.16, 344.53] |  81.61 [74.30, 84.45] | 2.44 [2.44, 2.44] |   0.14 [0.05, 0.55] | 210.61 [210.54, 210.63] | 46697.30 [44211.80, 52005.70] |
| async / main  | 68.17 [51.39, 83.70] | 209.15 [134.53, 368.39] | 373.23 [313.47, 457.30] | 88.78 [72.69, 114.21] | 2.44 [0.00, 2.44] |   0.37 [0.08, 0.88] | 212.36 [212.34, 212.36] | 43332.03 [31416.58, 52305.19] |
| async / final | 75.31 [53.81, 84.38] | 263.95 [165.03, 337.06] | 374.89 [308.25, 433.97] | 96.63 [76.01, 111.57] | 2.44 [0.00, 2.44] |   0.21 [0.12, 0.33] | 212.01 [211.96, 212.03] | 35884.13 [31808.04, 50728.10] |

#### Identity, cold

| API / build   |                  P50 µs |                  P95 µs |                     P99 µs |      Worker CPU µs/read |    Owner CPU µs/read |  MongoDB CPU µs/read |           Group PSS MiB |                       Reads/s |
| ------------- | ----------------------: | ----------------------: | -------------------------: | ----------------------: | -------------------: | -------------------: | ----------------------: | ----------------------------: |
| sync / main   | 244.27 [242.22, 246.22] | 479.66 [459.48, 495.66] |   910.07 [686.44, 1381.51] | 186.14 [184.44, 188.81] | 43.95 [41.50, 43.95] | 62.62 [59.20, 67.53] | 236.98 [236.96, 237.25] | 14042.42 [13953.96, 14746.80] |
| sync / final  | 242.63 [240.98, 245.00] | 597.88 [525.77, 660.59] |  1159.94 [986.20, 1429.67] | 195.37 [193.73, 196.67] | 46.39 [46.39, 48.83] | 63.46 [63.19, 65.54] | 237.14 [237.11, 237.14] | 13646.21 [13353.29, 13945.02] |
| async / main  | 324.51 [322.53, 331.82] | 721.73 [717.53, 915.00] | 1392.39 [1389.37, 1573.96] | 313.06 [310.85, 319.04] | 51.27 [48.83, 51.27] | 64.55 [64.33, 65.79] | 238.28 [238.15, 238.37] | 10312.05 [10139.80, 10647.86] |
| async / final | 323.69 [320.30, 327.22] | 724.63 [553.57, 732.26] |  1366.78 [870.54, 1443.27] | 312.65 [292.74, 314.89] | 51.27 [46.39, 53.71] | 63.69 [61.14, 63.89] | 238.37 [238.36, 238.48] | 10422.51 [10355.56, 11354.72] |

#### Identity, hot

| API / build   |            P50 µs |               P95 µs |               P99 µs |  Worker CPU µs/read | Owner CPU µs/read | MongoDB CPU µs/read |           Group PSS MiB |                          Reads/s |
| ------------- | ----------------: | -------------------: | -------------------: | ------------------: | ----------------: | ------------------: | ----------------------: | -------------------------------: |
| sync / main   | 6.82 [5.42, 7.63] |  21.00 [7.97, 25.32] |  25.77 [9.45, 32.36] |  8.63 [6.39, 10.03] | 0.61 [0.00, 0.61] |   0.02 [0.01, 0.03] | 212.73 [212.70, 212.88] | 444471.75 [335955.56, 523001.47] |
| sync / final  | 6.75 [5.46, 7.70] |  19.65 [9.84, 24.26] | 27.23 [11.08, 32.61] |  9.07 [6.31, 10.42] | 0.31 [0.31, 0.92] |   0.03 [0.00, 0.03] | 212.84 [212.82, 212.87] | 426762.32 [336889.59, 563024.82] |
| async / main  | 6.40 [5.99, 8.48] | 29.64 [25.74, 30.16] | 36.34 [33.26, 37.54] | 10.65 [9.89, 11.67] | 1.22 [0.61, 1.22] |   0.03 [0.02, 0.17] | 213.89 [213.88, 214.24] | 348911.80 [298734.01, 357923.52] |
| async / final | 8.08 [6.45, 8.14] | 24.50 [13.26, 31.05] | 32.11 [15.86, 36.85] | 10.00 [7.94, 10.80] | 0.92 [0.31, 1.22] |   0.21 [0.02, 0.40] | 213.90 [213.88, 213.96] | 378706.13 [341086.71, 405004.93] |

Cold sorted P50 decreases in all six pairs, by 21.3–28.0%. Measured
worker-plus-owner CPU decreases in all six pairs, by 6.2–14.2%, and throughput
increases by 23.1–29.6%. Sorted group PSS decreases in all twelve hot/cold pairs,
by 0.16–2.15 MiB. These findings resolve the rejected directory candidate's
resource costs for this configuration, not for every cache size or workload.
Async cold P95/P99 and hot statistics have mixed directions or overlapping
ranges; no universal tail or hot-read improvement is established.

Sync identity cold is the blocking exception: all three pairs have higher P95,
P99 and reader CPU and lower throughput. CPU ranges are separated. The native
find benefit cannot justify accepting that result.

### Registered sync identity controls

Six more alternating pairs use the same populations and calls, with sync only.
They are a separate acquisition, not pooled with the three original windows to
manufacture confidence intervals. All twelve windows are cache misses with zero
bypasses, zero synchronous owner requests and one stream.

| Build |                  P50 µs |                  P95 µs |                    P99 µs |      Worker CPU µs/read |    Owner CPU µs/read |  MongoDB CPU µs/read |           Group PSS MiB |                       Reads/s |
| ----- | ----------------------: | ----------------------: | ------------------------: | ----------------------: | -------------------: | -------------------: | ----------------------: | ----------------------------: |
| main  | 240.83 [235.41, 303.42] | 526.62 [371.68, 674.35] |  963.49 [526.50, 1168.99] | 183.10 [173.62, 200.72] | 41.50 [41.50, 48.83] | 60.10 [55.49, 63.37] | 237.12 [235.93, 237.22] | 13894.78 [11239.51, 15814.98] |
| final | 243.02 [237.44, 251.17] | 626.16 [374.01, 800.09] | 1153.31 [590.41, 1361.34] | 194.35 [173.47, 202.52] | 43.95 [39.06, 48.83] | 62.99 [56.81, 71.64] | 237.23 [237.15, 237.29] | 13317.42 [12967.24, 15350.08] |

Candidate P99 increases in all six controls (0.5–74.3%), hence all nine final
pairs. Control CPU directions vary; their ranges overlap and do not establish a
uniform CPU increase. The consistent tail direction remains unacceptable under
the nonregression requirement. No additional timing controls were run.

### Final attribution and evidence boundary

In separate sorted diagnostics, both builds accept all 1,024 admissions per
window, retain no owner captures and have zero timeout/failure/drop counters.
Final find admissions use the socket: native admissions are zero. Main sends
69,139,456 worker bytes and receives 66,560; final sends 69,159,856 and receives 260. Selection exchanges fall from 1,024 to four. Total sent bytes increase
slightly because the local-capture envelope is larger. Owner request deltas
include one observer request and must not be presented as pure worker traffic.

The identity transport diagnostic has identical traffic and outcomes in both
builds: 4,096 native queue admissions, zero selection requests or drops,
19,984,384 worker bytes sent, no worker bytes received, and 4,096 accepted
admissions. Both finish with 5,120 core entries and no evictions. Owner busy
wall time is 0.165 versus 0.183 seconds, motivating the bounded owner-profile
follow-up; it does not identify a cause by itself.

All four worker profiles per build were aggregated. For 1,024 profiled reads,
each build calls native lookup, capture and enqueue exactly 1,024 times and
`isinstance` 34,816 times. Native lookup/capture/enqueue times are near equal;
key preparation is also near equal. The larger candidate wall time is mainly
in MongoDB socket receive/send, not an extra worker selection or serialization
path. Profiles explain paths, not uninstrumented latency percentages.

One additional owner-only profile per build covers startup, warmup, measured
reads and shutdown. Counts differ (4,920 versus 4,542 admissions), so compare
normalized costs rather than raw totals. Cumulative `_admit_local` profile time
is 74.56 versus 75.18 µs/call. Native publication is 1.52 versus 1.46 µs/call;
native storage is 1.58 versus 1.57. These do not isolate the tail regression.
Both environments load byte-identical PyMongo and BSON C extensions. No further
architecture or measurement variants were attempted after this attribution.

The native implementation passes correctness, lifecycle, coverage and model
checks, but **fails the performance acceptance decision**. A native rewrite is
not promoted on a favorable sorted median while another supported path has an
unexplained consistent tail increase. The root cause remains unisolated; this
report does not assert that a specific native instruction caused the increase.

### Final existing-test comparison

All six runs execute the same 279 existing cases, excluding the newly added
cases as specified in the plan. External elapsed time is 70.82 [70.78, 71.10]
seconds for main and 70.68 [70.59, 72.24] for final. Paired differences are
+1.46, −0.23 and −0.42 seconds; no reproducible existing-test slowdown is
established. Acquisition and test logs have no failures or warnings. The
separately tracked Lychee warning above remains a development-tool issue.

## Reproduce the native trials

Use the build/venv commands in [the release baseline](results.md#reproduce) for
main and the frozen candidate revision named in each section. Run the same
collector from `a403bc50eed94a99566d91b0f14340b4803027f3` for both installed
builds. Native floors and saturation use `research/shared_find_misses/floors.py`
from that revision. These commands collect new observations; original raw
samples/profiles are not committed or promised to be independently recovered.

For the matched implementation comparison, build main and candidate from clean
checkouts using the [baseline wheel/venv commands](results.md#reproduce) with
separate report directories.
Run the collector from candidate source for **both** installed environments,
checking `client_query_cache.__file__` resolves inside the selected environment.
Do not use an editable install or put `src/` on `PYTHONPATH`. For each of three
blocks, run the [baseline identity/sorted commands](results.md#reproduce) with `--paths shared
--repetitions 1`. Use main then candidate with `--models sync async` in blocks
one and three; candidate then main with `--models async sync` in block two.
Store distinct filenames per build/block. For the final identity tail control, run
only `--method identity --hot-keys 1024 --samples 1024 --workloads cold --models
sync --paths shared --repetitions 1` for six more alternating revision pairs.

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

For saturation, add `--candidate --saturation` to the native floor command.
For identity transport diagnostics use `--method identity --hot-keys 1024
--samples 1024 --models sync --paths shared --workloads cold --repetitions 1
--diagnostics`, once per build. For separate worker profiles use `--samples 256`
and `--profile-dir "$REPORT_DIR/identity-profiles"` instead of `--diagnostics`.

The owner profile uses the same 256-call workload through this temporary
launcher, with `PYTHONPATH=.` and `CQC_OWNER_PROFILE` set to a distinct `.pstats`
path for each installed build. It profiles the spawned owner, while the ordinary
collector's `--profile-dir` profiles workers.

```python
import cProfile
import os
import client_query_cache.shared as shared
from benchmarks import public_shared_cache

original_owner = shared._owner_main


def profiled_owner(config, control):
    profiler = cProfile.Profile()
    try:
        profiler.runcall(original_owner, config, control)
    finally:
        profiler.dump_stats(os.environ["CQC_OWNER_PROFILE"])


shared._owner_main = profiled_owner
if __name__ == "__main__":
    public_shared_cache.main()
```
