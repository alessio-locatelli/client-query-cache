# Shared collection-read measurements

This comparison supports [issue #295](https://github.com/alessio-locatelli/client-query-cache/issues/295). It measures the implementation in this change against `main` at [`ff9153499b5e00054a2b91cf17cc852522cd13b1`](https://github.com/alessio-locatelli/client-query-cache/commit/ff9153499b5e00054a2b91cf17cc852522cd13b1), direct PyMongo majority reads and independent process-local caches.

## Conditions and limits

Measured on 2026-10-18 with CPython 3.14.7, PyMongo 4.19.0, Fedora 44, Linux 7.2.10, glibc 2.43 and an Intel Core i3-13100 with eight logical CPUs. Both revisions used release Linux wheels built on this host. The existing `benchmarks/public_shared_cache.py` harness ran four spawned workers against its disposable pinned MongoDB 9.0.2 replica set, limited to two CPUs and 1 GiB. Tests and builds were stopped during timing.

The shared owner has a 32 MiB budget, 40 MiB arena and 16,384 slots; independent managers retain their default 64 MiB per worker. Hot sets fit both configurations. A barrier starts measured reads after warmup, and two finish barriers keep workers and mappings alive while memory is sampled. Worker CPU timing ends before PSS inspection. Reader CPU sums workers and the shared owner during the measured interval, including concurrent stream/publication work; it excludes initialization, teardown, the writer and MongoDB. MongoDB CPU is reported separately. PSS sums workers and owner, excluding MongoDB and the harness/writer parent.

There are 240 initial windows: 72 identity comparison windows (three alternating revision pairs), 72 small-result windows, 60 larger-result windows and 36 concurrent-write windows. Each new-method configuration has one window per API/path/workload: these are bounded observations, not replicated estimates of universal P99 or a general performance ranking. Hot/cold samples and resources match across paths. Each window records actual cache hits, misses and bypasses; every caching path had zero bypasses. Timing output remains untracked and disposable. The summary cannot recover individual samples; the commands below produce fresh measurements.

## Existing-path comparison

Three paired identity runs used 1,024 calls per worker, 128 hot keys and 4,096-byte payloads. The table contains medians of the three window statistics, **main → implementation**. Both cached paths had exactly 4,096 hits in every hot window and 4,096 misses in every cold window.

| API   | Workload | Path        |       Median µs |            P99 µs |  Reader CPU s |
| ----- | -------- | ----------- | --------------: | ----------------: | ------------: |
| sync  | hot      | direct      | 157.98 → 159.43 |   261.45 → 259.19 | 0.444 → 0.449 |
| sync  | hot      | independent |   33.47 → 34.12 |     72.04 → 92.25 | 0.149 → 0.151 |
| sync  | hot      | shared      |   26.46 → 25.14 |     53.09 → 50.07 | 0.124 → 0.122 |
| sync  | cold     | direct      | 159.59 → 159.11 |   258.38 → 243.02 | 0.446 → 0.450 |
| sync  | cold     | independent | 232.57 → 229.05 | 1050.35 → 1146.15 | 0.876 → 0.873 |
| sync  | cold     | shared      | 226.10 → 224.98 | 1212.89 → 1129.42 | 1.042 → 1.040 |
| async | hot      | direct      | 227.94 → 227.94 |   479.69 → 422.48 | 0.838 → 0.836 |
| async | hot      | independent |   29.34 → 30.37 |     88.25 → 60.26 | 0.140 → 0.125 |
| async | hot      | shared      |   26.79 → 26.96 |     52.05 → 54.27 | 0.130 → 0.119 |
| async | cold     | direct      | 233.56 → 233.08 |   422.41 → 378.38 | 0.844 → 0.852 |
| async | cold     | independent | 314.38 → 313.20 | 1398.99 → 1484.34 | 1.328 → 1.339 |
| async | cold     | shared      | 300.88 → 304.95 | 1580.74 → 1663.57 | 1.522 → 1.512 |

The initial async shared cold median increased by 1.4%; three targeted repeats also moved upward (307.39 → 315.39 µs). That result triggered profiling and direct-read controls, rather than acceptance as a regression. Four profiling windows used 1,024 warmed keys: both revisions executed 4,096 local selections, key preparations and admissions, with no identity selection RPCs. The incarnation-bearing owner handles therefore add no operation to this existing path.

Twelve unprofiled cold control windows with 1,024 warmed keys reversed the direction in two of three pairs: shared median-of-medians was 303.77 → 303.54 µs, with reader CPU 1.463 → 1.365 seconds. Another twelve control windows restored the original 128-key conditions: shared median-of-medians was 308.08 → 306.84 µs, P99 1,607.10 → 1,530.17 µs, reader CPU 1.536 → 1.496 seconds and throughput 10,612 → 11,018 reads/second. Direct controls were 236.63 → 236.11 µs. This did not establish a source-caused cold-path slowdown.

Thirty targeted repeat windows also extended hot identity measurements to 8,192 calls per worker. Shared medians were 8.66 → 6.65 µs sync and 9.38 → 6.97 µs asyncio. Independent medians were 8.03 → 8.18 µs and 8.75 → 8.81 µs; CPU, P99 and throughput moved in different directions across repetitions. Short hot windows were particularly variable, so these observations do not establish a general ranking or rule out effects smaller than that variability.

The immutable codec-identity reuse also affects existing process-local methods. An initial 24-window comparison with 32 hot keys showed large, inconsistent changes. A further 48 matched windows used 1,024 warmed keys and 1,024 calls per worker (255 calls for cold estimated counts to fit namespace capacity). Each cell below is **main → implementation**. Cold cached calls had zero hits, hot calls were all hits, and bypasses were zero.

| Method                     | API   | Hot median µs | Cold median µs | Hot reader CPU s | Cold reader CPU s |
| -------------------------- | ----- | ------------: | -------------: | ---------------: | ----------------: |
| `find_one`                 | sync  |   58.4 → 47.9 |  303.8 → 297.8 |    0.260 → 0.257 |     1.066 → 0.997 |
| `find_one`                 | async |   46.0 → 54.7 |  389.8 → 386.6 |    0.266 → 0.303 |     1.525 → 1.552 |
| `find`                     | sync  |   44.3 → 52.5 |  331.4 → 330.8 |    0.322 → 0.235 |     1.082 → 1.214 |
| `find`                     | async |   53.6 → 55.4 |  416.9 → 416.9 |    0.324 → 0.361 |     1.663 → 1.645 |
| `aggregate`                | sync  |   51.6 → 55.8 |  355.4 → 335.4 |    0.280 → 0.327 |     1.095 → 1.044 |
| `aggregate`                | async |   50.5 → 54.3 |  424.0 → 424.0 |    0.292 → 0.267 |     1.517 → 1.571 |
| `count_documents`          | sync  |   43.1 → 45.7 |  379.1 → 374.3 |    0.237 → 0.230 |     0.935 → 0.878 |
| `count_documents`          | async |   37.7 → 42.2 |  467.5 → 466.9 |    0.166 → 0.192 |     1.436 → 1.415 |
| `estimated_document_count` | sync  |   26.9 → 26.8 |  337.7 → 291.4 |    0.034 → 0.034 |     0.315 → 0.268 |
| `estimated_document_count` | async |   23.0 → 14.8 |  297.5 → 377.8 |    0.024 → 0.022 |     0.448 → 0.431 |
| `distinct`                 | sync  |   45.3 → 39.2 |  265.5 → 259.4 |    0.188 → 0.207 |     0.864 → 0.869 |
| `distinct`                 | async |   38.1 → 13.2 |  347.1 → 346.5 |    0.208 → 0.057 |     1.342 → 1.270 |

Hot latency and CPU changes were not consistent between the smaller and larger windows, including methods whose per-read execution is unchanged. The codec change removes repeated fingerprint construction; these noisy windows do not quantify its benefit. Cold medians for the five filtered methods were equal or lower in the larger windows. No general improvement over main is claimed from these single-window local-method comparisons.

Existing shared test files completed in 115.76 seconds on main and 116.80 seconds on the implementation, then 116.02 seconds on the implementation and 117.21 seconds on main with reversed order. The direction reversed; new tests were excluded. The full functional/coverage gate and the real multi-worker FastAPI self-check passed.

The complete bounded investigation comprises 370 windows: 240 initial measurements plus 130 targeted existing-path/control/profiling windows. It did not change cache defaults or defer an identified regression.

## New methods without writes

Tables use **D / I / S** for direct PyMongo / independent caches / shared cache. Every hot caching window recorded 512 hits and zero misses; every cold caching window recorded 512 misses and zero hits. There are 128 measured calls per worker and 32 hot query keys. Cold filters select different seeded groups for each worker. Estimated counts have one hot collection; cold calls use different pre-created collections, with collection metadata warmed by an unrelated identity read before the measured interval.

Small results use one document per group with a 256-byte payload. Larger results use eight documents per group with 4,096-byte payloads: `find` and `aggregate` return all eight, `distinct` returns eight different payload values, sorted `find_one` returns one document, and `count_documents` returns a scalar count over eight documents. These are changes to both result size and collection cardinality, not an isolated document-size experiment. Estimated counts return a scalar in both cases, so no duplicate larger-result window was needed.

### Small results, hot

| Method                     | API   |   Median µs D / I / S |      P99 µs D / I / S | Reader CPU s D / I / S | MongoDB CPU s D / I / S |     PSS MiB D / I / S |
| -------------------------- | ----- | --------------------: | --------------------: | ---------------------: | ----------------------: | --------------------: |
| `find_one`                 | sync  |   213.3 / 95.4 / 60.9 | 322.1 / 225.8 / 181.0 |  0.064 / 0.066 / 0.042 |   0.036 / 0.000 / 0.000 | 160.1 / 160.6 / 199.0 |
| `find_one`                 | async |  289.1 / 47.6 / 102.1 |  523.8 / 81.4 / 250.4 |  0.114 / 0.025 / 0.070 |   0.039 / 0.000 / 0.000 | 161.6 / 161.9 / 200.3 |
| `find`                     | sync  | 207.3 / 154.9 / 149.6 | 348.3 / 424.0 / 458.3 |  0.064 / 0.087 / 0.094 |   0.035 / 0.000 / 0.000 | 160.2 / 160.7 / 199.1 |
| `find`                     | async | 273.9 / 164.6 / 158.1 | 537.0 / 344.7 / 539.3 |  0.118 / 0.092 / 0.102 |   0.031 / 0.000 / 0.001 | 161.6 / 161.9 / 200.3 |
| `aggregate`                | sync  |  237.0 / 117.3 / 95.3 | 399.8 / 212.6 / 212.1 |  0.062 / 0.064 / 0.057 |   0.049 / 0.000 / 0.000 | 160.1 / 160.6 / 199.0 |
| `aggregate`                | async | 308.1 / 104.8 / 125.7 | 580.7 / 233.7 / 307.5 |  0.110 / 0.063 / 0.078 |   0.048 / 0.000 / 0.001 | 161.4 / 161.8 / 200.2 |
| `count_documents`          | sync  |   299.5 / 33.9 / 74.4 | 469.1 / 154.1 / 153.8 |  0.060 / 0.027 / 0.042 |   0.084 / 0.000 / 0.000 | 160.1 / 160.5 / 198.9 |
| `count_documents`          | async |   371.9 / 56.6 / 54.0 | 653.3 / 152.5 / 105.3 |  0.112 / 0.036 / 0.031 |   0.085 / 0.000 / 0.000 | 161.4 / 161.7 / 200.2 |
| `estimated_document_count` | sync  |   127.2 / 28.7 / 25.0 |  269.7 / 122.1 / 62.3 |  0.042 / 0.018 / 0.015 |   0.017 / 0.000 / 0.000 | 160.1 / 160.4 / 198.6 |
| `estimated_document_count` | async |   197.8 / 16.7 / 20.0 |   406.8 / 25.2 / 52.1 |  0.087 / 0.009 / 0.013 |   0.020 / 0.000 / 0.000 | 161.4 / 161.6 / 199.8 |
| `distinct`                 | sync  |   203.3 / 35.0 / 51.2 | 394.0 / 107.6 / 120.9 |  0.053 / 0.024 / 0.033 |   0.040 / 0.000 / 0.000 | 160.1 / 160.6 / 198.8 |
| `distinct`                 | async |   246.4 / 52.3 / 80.1 | 614.3 / 146.9 / 189.0 |  0.096 / 0.034 / 0.042 |   0.035 / 0.000 / 0.000 | 161.4 / 161.7 / 200.1 |

### Small results, cold

| Method                     | API   |   Median µs D / I / S |        P99 µs D / I / S | Reader CPU s D / I / S | MongoDB CPU s D / I / S |     PSS MiB D / I / S |
| -------------------------- | ----- | --------------------: | ----------------------: | ---------------------: | ----------------------: | --------------------: |
| `find_one`                 | sync  | 224.8 / 649.8 / 886.3 | 407.1 / 1666.3 / 2951.8 |  0.064 / 0.256 / 0.454 |   0.038 / 0.099 / 0.103 | 160.2 / 161.4 / 202.3 |
| `find_one`                 | async | 288.7 / 610.9 / 705.6 | 522.9 / 2009.2 / 3427.8 |  0.117 / 0.312 / 0.518 |   0.036 / 0.085 / 0.085 | 161.6 / 162.8 / 203.7 |
| `find`                     | sync  | 215.2 / 635.4 / 656.7 | 332.6 / 2380.9 / 2251.4 |  0.065 / 0.289 / 0.336 |   0.037 / 0.095 / 0.063 | 160.1 / 161.6 / 203.4 |
| `find`                     | async | 299.9 / 640.1 / 837.2 | 551.5 / 2786.4 / 3620.3 |  0.118 / 0.359 / 0.555 |   0.044 / 0.083 / 0.085 | 161.5 / 162.8 / 205.0 |
| `aggregate`                | sync  | 242.3 / 706.5 / 624.0 | 417.6 / 2024.4 / 2813.9 |  0.063 / 0.281 / 0.387 |   0.050 / 0.135 / 0.104 | 160.0 / 161.5 / 203.4 |
| `aggregate`                | async | 314.9 / 662.4 / 783.7 | 569.2 / 2143.3 / 3926.0 |  0.113 / 0.343 / 0.519 |   0.053 / 0.114 / 0.108 | 161.4 / 162.8 / 204.7 |
| `count_documents`          | sync  | 305.0 / 595.7 / 837.8 | 459.7 / 2010.4 / 3554.6 |  0.060 / 0.210 / 0.371 |   0.085 / 0.192 / 0.196 | 160.1 / 161.0 / 201.7 |
| `count_documents`          | async | 384.7 / 757.7 / 787.9 | 680.8 / 2210.5 / 4611.1 |  0.112 / 0.296 / 0.495 |   0.085 / 0.186 / 0.183 | 161.4 / 162.2 / 203.0 |
| `estimated_document_count` | sync  | 138.5 / 325.0 / 546.9 |  290.7 / 693.9 / 2636.9 |  0.043 / 0.126 / 0.281 |   0.019 / 0.041 / 0.067 | 160.4 / 162.2 / 203.1 |
| `estimated_document_count` | async | 213.4 / 665.1 / 685.9 | 354.7 / 1578.2 / 2088.0 |  0.097 / 0.322 / 0.422 |   0.025 / 0.058 / 0.054 | 161.9 / 163.5 / 204.3 |
| `distinct`                 | sync  | 198.9 / 576.1 / 769.3 | 352.4 / 1359.9 / 2446.4 |  0.051 / 0.195 / 0.392 |   0.040 / 0.097 / 0.106 | 160.1 / 161.1 / 201.7 |
| `distinct`                 | async | 287.2 / 559.4 / 692.1 | 525.5 / 2256.9 / 2484.2 |  0.104 / 0.291 / 0.410 |   0.042 / 0.092 / 0.078 | 161.4 / 162.3 / 203.0 |

### Large results, hot

| Method            | API   |   Median µs D / I / S |      P99 µs D / I / S | Reader CPU s D / I / S | MongoDB CPU s D / I / S |     PSS MiB D / I / S |
| ----------------- | ----- | --------------------: | --------------------: | ---------------------: | ----------------------: | --------------------: |
| `find_one`        | sync  |   211.9 / 93.6 / 82.6 | 403.8 / 164.1 / 193.3 |  0.063 / 0.049 / 0.051 |   0.036 / 0.000 / 0.011 | 160.2 / 160.6 / 199.1 |
| `find_one`        | async |  323.8 / 98.9 / 148.4 | 621.5 / 230.6 / 205.6 |  0.124 / 0.061 / 0.070 |   0.040 / 0.000 / 0.000 | 161.6 / 161.8 / 200.4 |
| `find`            | sync  | 270.3 / 183.2 / 210.0 | 453.0 / 476.9 / 459.0 |  0.077 / 0.109 / 0.126 |   0.046 / 0.000 / 0.001 | 160.2 / 164.4 / 200.4 |
| `find`            | async | 335.9 / 168.5 / 213.3 | 591.2 / 397.5 / 438.7 |  0.130 / 0.098 / 0.122 |   0.047 / 0.000 / 0.001 | 161.6 / 165.6 / 201.8 |
| `aggregate`       | sync  | 277.0 / 139.8 / 157.9 | 416.6 / 285.6 / 258.4 |  0.073 / 0.078 / 0.084 |   0.057 / 0.000 / 0.001 | 160.1 / 164.5 / 200.3 |
| `aggregate`       | async | 371.4 / 140.9 / 154.9 | 662.5 / 294.1 / 238.1 |  0.126 / 0.080 / 0.080 |   0.063 / 0.000 / 0.000 | 161.4 / 165.6 / 201.6 |
| `count_documents` | sync  |   316.3 / 60.1 / 67.1 | 533.4 / 104.9 / 192.3 |  0.063 / 0.032 / 0.045 |   0.088 / 0.000 / 0.000 | 160.2 / 160.5 / 199.0 |
| `count_documents` | async |   407.7 / 64.0 / 68.1 | 740.7 / 119.0 / 221.2 |  0.114 / 0.036 / 0.043 |   0.089 / 0.000 / 0.000 | 161.5 / 161.8 / 200.1 |
| `distinct`        | sync  |  257.6 / 65.5 / 102.4 | 463.6 / 126.8 / 202.6 |  0.063 / 0.038 / 0.072 |   0.049 / 0.000 / 0.000 | 160.1 / 164.2 / 200.1 |
| `distinct`        | async |  319.2 / 67.3 / 102.0 | 589.7 / 181.9 / 188.9 |  0.113 / 0.043 / 0.055 |   0.049 / 0.000 / 0.000 | 161.4 / 165.4 / 201.3 |

### Large results, cold

| Method            | API   |   Median µs D / I / S |        P99 µs D / I / S | Reader CPU s D / I / S | MongoDB CPU s D / I / S |     PSS MiB D / I / S |
| ----------------- | ----- | --------------------: | ----------------------: | ---------------------: | ----------------------: | --------------------: |
| `find_one`        | sync  | 221.6 / 716.5 / 689.8 | 385.7 / 1906.8 / 3700.6 |  0.065 / 0.281 / 0.412 |   0.039 / 0.110 / 0.097 | 160.2 / 163.0 / 204.5 |
| `find_one`        | async | 305.7 / 652.4 / 746.6 | 652.9 / 2166.3 / 3204.8 |  0.117 / 0.328 / 0.447 |   0.042 / 0.086 / 0.080 | 161.6 / 164.5 / 205.9 |
| `find`            | sync  | 280.2 / 520.9 / 638.1 | 466.2 / 2863.1 / 1096.6 |  0.079 / 0.282 / 0.281 |   0.047 / 0.097 / 0.052 | 160.2 / 181.4 / 223.2 |
| `find`            | async | 348.9 / 681.2 / 882.9 | 716.0 / 2470.8 / 4549.1 |  0.130 / 0.380 / 0.619 |   0.057 / 0.097 / 0.106 | 161.5 / 183.0 / 224.7 |
| `aggregate`       | sync  | 300.3 / 688.7 / 619.4 | 525.4 / 2257.3 / 2825.5 |  0.076 / 0.290 / 0.342 |   0.066 / 0.135 / 0.091 | 160.1 / 181.4 / 223.3 |
| `aggregate`       | async | 370.4 / 684.9 / 841.9 | 719.4 / 2867.8 / 3317.3 |  0.126 / 0.361 / 0.520 |   0.063 / 0.129 / 0.117 | 161.4 / 182.8 / 224.8 |
| `count_documents` | sync  | 296.9 / 774.3 / 923.9 | 482.1 / 2058.1 / 3511.9 |  0.058 / 0.224 / 0.394 |   0.083 / 0.205 / 0.212 | 160.1 / 161.0 / 201.7 |
| `count_documents` | async | 399.1 / 737.6 / 714.5 | 744.8 / 2271.2 / 4187.6 |  0.112 / 0.297 / 0.430 |   0.087 / 0.182 / 0.166 | 161.4 / 162.3 / 202.9 |
| `distinct`        | sync  | 250.6 / 704.9 / 554.0 | 404.2 / 1918.4 / 2909.6 |  0.061 / 0.251 / 0.340 |   0.050 / 0.129 / 0.103 | 160.1 / 180.8 / 220.8 |
| `distinct`        | async | 341.5 / 635.3 / 671.0 | 581.3 / 3137.9 / 3291.0 |  0.116 / 0.306 / 0.506 |   0.055 / 0.104 / 0.109 | 161.4 / 182.0 / 222.4 |

All measured shared hot medians were below direct reads. Independent caches often used less reader CPU or had lower hot latency; sharing does not establish a general per-worker speed advantage. Cold admission increases latency and CPU substantially relative to direct reads. With only 32 hot query keys, the owner adds roughly 38–39 MiB to combined PSS instead of producing a memory saving. Larger cold cursor/distinct results retain more data in both cache configurations. These measurements support reusing shared results across workers while making the miss and small-working-set costs explicit.

## Concurrent writes at a matching read rate

Each window requests 2,000 reads/second across four workers for 256 calls per worker, with eight 256-byte-payload documents per group and 32 hot keys. A prepared writer updates one document in group zero every 20 ms; all paths completed 21 writes. Actual throughput was 1,978–2,004 reads/second. The writer changes a field outside the group predicate, so broad namespace invalidation is deliberately conservative. There is no read-after-write assertion in this latency workload; real-stream correctness and admission races are covered by integration tests.

CPU below sums reader, MongoDB and writer/harness-parent CPU during the interval. The parent primarily runs the writer and barriers; memory remains worker-plus-owner PSS. Hit percentages are measured outcomes, not modeled reuse.

| Method                     | API   |      Median µs D / I / S |         P99 µs D / I / S | Total CPU s D / I / S |     PSS MiB D / I / S | Hit % I / S |
| -------------------------- | ----- | -----------------------: | -----------------------: | --------------------: | --------------------: | ----------: |
| `find_one`                 | sync  | 1089.9 / 1353.4 / 1332.4 | 1342.9 / 2049.4 / 2582.6 | 1.037 / 1.472 / 1.469 | 160.2 / 160.8 / 199.0 |   1.6 / 1.2 |
| `find_one`                 | async | 1090.8 / 1546.7 / 1807.4 | 2081.8 / 2974.9 / 2966.4 | 1.284 / 1.677 / 1.860 | 161.6 / 162.2 / 200.5 |  2.0 / 10.0 |
| `find`                     | sync  | 1136.5 / 1357.6 / 1563.6 | 1476.1 / 2442.5 / 2789.9 | 1.069 / 1.492 / 1.601 | 160.2 / 160.8 / 199.2 |   2.0 / 2.1 |
| `find`                     | async | 1023.7 / 1627.4 / 1752.7 | 1871.7 / 2983.4 / 3165.9 | 1.203 / 1.754 / 1.892 | 161.6 / 162.0 / 200.5 |   2.0 / 8.5 |
| `aggregate`                | sync  | 1061.2 / 1547.5 / 1556.4 | 1574.2 / 2579.9 / 2659.9 | 0.995 / 1.640 / 1.550 | 160.2 / 160.8 / 199.2 |   2.0 / 2.6 |
| `aggregate`                | async | 1143.4 / 1613.0 / 1644.2 | 1920.4 / 2974.3 / 3238.8 | 1.321 / 1.790 / 1.807 | 161.4 / 162.0 / 200.5 |   2.0 / 8.3 |
| `count_documents`          | sync  | 1246.9 / 1607.0 / 1638.2 | 2119.4 / 2698.5 / 2912.2 | 1.200 / 1.638 / 1.630 | 160.1 / 160.7 / 199.0 |   2.0 / 2.1 |
| `count_documents`          | async | 1304.2 / 1636.4 / 1696.7 | 2570.4 / 3018.3 / 3580.6 | 1.428 / 1.737 / 1.845 | 161.5 / 161.9 / 200.2 |  2.0 / 10.5 |
| `estimated_document_count` | sync  |      702.5 / 63.2 / 69.2 | 1172.3 / 1442.0 / 2075.6 | 0.641 / 0.375 / 0.323 | 160.1 / 160.6 / 198.7 | 91.8 / 91.8 |
| `estimated_document_count` | async |      916.4 / 80.2 / 75.3 | 2017.1 / 1777.4 / 2311.9 | 1.103 / 0.519 / 0.443 | 161.5 / 161.7 / 199.9 | 92.2 / 91.8 |
| `distinct`                 | sync  | 1041.9 / 1287.9 / 1189.6 | 1850.0 / 2263.8 / 2751.7 | 0.970 / 1.354 / 1.185 | 160.1 / 160.7 / 199.0 |   2.0 / 1.6 |
| `distinct`                 | async | 1053.5 / 1482.8 / 1613.7 | 2668.5 / 3474.0 / 3244.8 | 1.225 / 1.634 / 1.745 | 161.5 / 161.9 / 200.3 |   2.0 / 9.6 |

The broader filtered shapes repeatedly lose their 32-key working set after each write: shared hit rates were 1.2–10.5%, and caching cost more than direct reads. Estimated counts reuse a single namespace key between writes and reached 91.8% shared hits, with lower median latency and CPU than direct reads. Choose shared caching for reused reads and measure the application’s write rate and working set; these finite observations do not justify changing the explicit manager choice or consistency guarantees.

## Reproduce

Run the current harness from the implementation checkout for **both** wheels. Build the baseline wheel from the pinned main commit in a detached worktree and the implementation wheel from this change:

```bash
git worktree add --detach /tmp/agents/collection-read-main \
  ff9153499b5e00054a2b91cf17cc852522cd13b1
(cd /tmp/agents/collection-read-main && \
  uv run maturin build --release --compatibility linux \
  --out /tmp/agents/collection-read-main-wheel)
uv run maturin build --release --compatibility linux \
  --out /tmp/agents/collection-read-branch-wheel
```

These are same-host comparison wheels. The normal release build remains `just build`. Use the repository’s [development environment](https://github.com/alessio-locatelli/client-query-cache/blob/main/CONTRIBUTING.md) for the container runtime; the harness accepts no production URI.

For each wheel, run this identity window set in three alternating revision pairs:

```bash
comparison_wheel=/tmp/agents/collection-read-branch-wheel/client_query_cache-0.8.1-cp314-abi3-linux_x86_64.whl
uv run --quiet --isolated --no-project --python 3.14.7 \
  --with "$comparison_wheel" --with pymongo==4.19.0 \
  --with psutil --with testcontainers --with requests --with pyyaml \
  python -m benchmarks.public_shared_cache \
  --method identity --repetitions 1 --samples 1024 --hot-keys 128 \
  --document-bytes 4096 --output /tmp/agents/collection-read-identity.json
```

For new methods, substitute each of `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count` and `distinct`, using the implementation wheel and unique output filenames:

- Small: `--samples 128 --hot-keys 32 --document-bytes 256`.
- Larger: `--samples 128 --hot-keys 32 --result-documents 8 --document-bytes 4096`, excluding estimated counts.
- Writes: `--samples 256 --hot-keys 32 --result-documents 8 --document-bytes 256 --workloads hot --read-rate 2000 --write-interval 0.02`.

Keep `--repetitions 1` for these bounded configurations. Models and paths default to both APIs and all three comparison paths. Cold estimated counts require at most 255 samples per worker because each call needs a distinct collection. The JSON includes PyMongo version, actual hits/misses/bypasses, streams, throughput, latency, CPU and memory.

For the targeted identity repeats, use both wheels in alternating order:

- Hot: `--method identity --samples 8192 --hot-keys 128 --models sync async --paths independent shared --workloads hot`, three pairs.
- Initial cold repeat: `--method identity --samples 1024 --hot-keys 128 --models async --paths shared --workloads cold`, three pairs.
- Cold controls: `--method identity --samples 1024 --models async --paths direct shared --workloads cold`, three pairs with `--hot-keys 1024` and three with `--hot-keys 128`.
- Profiling: the 1,024-key cold control flags plus `--profile-dir /tmp/agents/collection-read-profiles`, one pair. Inspect worker `*.pstats` separately from unprofiled latency.
- Initial local-method controls: each of the six methods with `--paths independent --samples 128 --hot-keys 32 --document-bytes 256`, main wheel only; compare with the initial implementation windows.
- Larger local-method controls: each method with `--paths independent --samples 1024 --hot-keys 1024 --document-bytes 256`, one pair; use `--samples 255` for estimated counts.

Use distinct output/profile paths for each revision and repetition. Identity repeats retain 4,096-byte payloads.

Existing-test timing used `tests/shared_cache/test_public.py`, `test_sorted_find.py` and `test_scenarios.py` in each checkout, with the same development environment and four pytest workers. New tests in `test_collection_reads.py` were excluded from that comparison. Run the project’s `just pytest` recipe with those paths; a native extension built from the corresponding revision is required. Remove the disposable baseline worktree with `git worktree remove` after use.
