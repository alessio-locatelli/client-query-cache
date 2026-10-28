# Native process-local cache evaluation

The native prototype is unqualified under the registered stopping rule. Its
corrected complete-read CPU reduction has a 24.7% median, but one valid block
improves only 7.95%, below the required 10% in every block. Long-key incremental
warm PSS falls about 2.7%, below the alternative 20% threshold. The correction
substantially improves allocation lifetime, while synchronous long-key memory
after normal close remains higher than main in every block.

Keep ordinary process-local construction on the reference core. The measured
native implementation, tests and selection tools are preserved in published
history; experimental runtime code and private selection hooks are removed from
the delivered tree. The conditional ordinary-native integration and F/M controls
are inapplicable because no candidate qualifies. No final-native wheel is claimed.

The [acquisition plan](plan.md) owns workload definitions, environment, commands,
conformance mapping, stopping conditions, and diagnostic history. Raw outputs
remain untracked under its session directory. These results concern one host
and the registered workloads, rather than an application-wide speedup.

## Immutable sources

| Identity | Source                                                                                                            | Role                                                                     |
| -------- | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| M        | [1f70de76](https://github.com/alessio-locatelli/client-query-cache/tree/1f70de76b6bc9fdcc4ab7cf0d4a8a4d784d9588e) | Frozen ordinary main wheel                                               |
| C1       | [a7c91530](https://github.com/alessio-locatelli/client-query-cache/tree/a7c91530bcb069dea25f0de8432cdd8f7284f66a) | Initial candidate and acquisition source; R and N use this same wheel    |
| U        | [8de2aae1](https://github.com/alessio-locatelli/client-query-cache/tree/8de2aae1d36519fd7e1996caa7cb254a64368dad) | Versioned uncertainty subset; installed runtime remains C1               |
| C2a      | [effca8d8](https://github.com/alessio-locatelli/client-query-cache/tree/effca8d862bde060dd12cf7a2cc269a7be66f04f) | Interned-name diagnostic snapshot, without a qualifying cohort           |
| C2b      | [feb0b37e](https://github.com/alessio-locatelli/client-query-cache/tree/feb0b37ed439e7c8a3258c748fc2a7e05ccb6310) | Inline-node allocation correction, before final acquisition validation   |
| C2       | [de8408aa](https://github.com/alessio-locatelli/client-query-cache/tree/de8408aa3cde0ba2c674c253458975eacac84d81) | Frozen corrected source and acquisition setup for the second full cohort |

C1's published experiment tag was retrieved into a fresh checkout and its HEAD
verified before any proposed removal. Its wheel SHA-256 is
`791528a08521fc3a1620886aa71d819caa8f4d8cb0cd97ae9775c1f7f9d991bd`.
M's wheel SHA-256 is
`85fa6e72c5526006fb051e7f96efe864b80e4d823a4716d1a700da70326128b7`.
Per-revision provenance records retain imported paths, extension digests,
dependencies, clocks, and limits. Source URLs alone are not build hashes.

C2 is published as
[`experiment/native-process-local-cache-corrected-de8408aa`](https://github.com/alessio-locatelli/client-query-cache/tree/experiment/native-process-local-cache-corrected-de8408aa).
A fresh clone resolved that tag to the exact C2 commit before removal. Its wheel
SHA-256 is `e6ce7d763b423955b88577444ce4eeea54de6fdff0d86e34031a10ed161960b2`;
the extension SHA-256 is
`541606d9913bbc9079df71c54361c91801054bd7d893f274824e009b76bd0cab`.

## Initial five-block result

All 600 public windows, 1,860 memory checkpoints, and 30 contention windows
completed with their registered observations. The registered CPU target is
synchronous generic `find_one`, hot, through four independent managers. Values
below include reader supervision and divide by completed reads; MongoDB CPU is
separate. Negative changes mean less CPU.

| Block | M µs/read | R µs/read | N µs/read | N/M change | N/R change |
| ----- | --------: | --------: | --------: | ---------: | ---------: |
| 0     |    24.483 |    25.648 |    19.661 |    −19.70% |    −23.34% |
| 1     |    24.537 |    24.571 |    19.439 |    −20.78% |    −20.88% |
| 2     |    24.801 |    23.172 |    17.539 |    −29.28% |    −24.31% |
| 3     |    25.167 |    23.324 |    20.743 |    −17.58% |    −11.06% |
| 4     |    24.784 |    26.460 |    17.401 |    −29.79% |    −34.23% |

The CPU target passes its 10% threshold in all five blocks against both controls.
This is a positive measured result even though the resource gate blocks
retention. Incremental long-key warm PSS saves only 2.01–2.03% synchronously
and 1.94–1.96% asynchronously against M, far below the registered 20% threshold.
Every corresponding warm cache held 64,001 entries and 3,776,008 BSON bytes;
the full catalogue traversal hit with zero bypasses. Cold controls reached the
same 71,089-entry eviction boundary and 4,194,251 charged bytes.

Post-close long-key PSS exposes the principal regression. Median single-process
PSS was 127.66 versus 67.75 MiB synchronously and 179.62 versus 97.48 MiB
asynchronously for N versus M. Even after the harness's explicit diagnostic
`malloc_trim`, medians were 112.46 versus 65.56 MiB and 164.29 versus 97.41 MiB.
These are full process observations, not Python heap estimates. Resident counts
and native ownership diagnostics reached zero after close; the observations do
not by themselves establish an unreachable-object leak.

Other complete-read CPU controls mostly improved. Sorted-result and tail-latency
controls varied by block, including direct MongoDB controls. The initial async
small-entry hot P99 change had a +29.7% median with a −27.1% to +140.0% range;
it could not be dismissed merely because its median latency and CPU improved.
The separate uncertainty acquisition below retains this negative evidence.

Both contention topologies completed all 80,000 offered reads per window and
processed 1,000 invalidations overlapping actual reads. Bypass counts were zero;
998–1,000 reads missed as updates invalidated resident entries. Offered throughput
was about 4,000 reads/s, so equal throughput here is a load control rather than
proof of equal saturation capacity. Native CPU was lower in every initial block;
four-thread tails had mixed directions.

The frozen 4,367-node existing-test set completed with 4,366 passes and one
explicit real-server skip per valid run. M/R/N durations overlapped, approximately
1,278–1,295 seconds. These N runs retain reference-only internal-storage probes
and select native for actual manager paths; they are not a claim that every
direct-core test used native. Added native conformance runs are separate.

### Initial complete-read controls

N/M percentage changes below are medians and full ranges of paired-block
changes; individual requests are not statistical replications.

| Read / model / state         | CPU/read change      | P50 change           | P95 change           | P99 change            | Throughput change    |
| ---------------------------- | -------------------- | -------------------- | -------------------- | --------------------- | -------------------- |
| identity / sync / hot        | -32.6 [-36.7, -14.4] | -32.5 [-33.0, -31.1] | -37.7 [-52.3, +20.0] | -41.4 [-51.6, -9.9]   | +51.3 [+0.8, +62.8]  |
| identity / sync / cold       | -11.2 [-11.3, -9.5]  | -7.2 [-9.1, -7.0]    | -12.3 [-18.0, +21.0] | -17.8 [-33.7, +11.7]  | +11.0 [+4.0, +11.9]  |
| identity / async / hot       | -29.3 [-37.1, -25.8] | -29.9 [-31.1, -29.1] | -41.3 [-64.1, -15.2] | -37.0 [-55.5, -21.1]  | +31.4 [+26.1, +71.4] |
| identity / async / cold      | -7.7 [-10.5, -6.2]   | -7.2 [-8.7, -4.8]    | -12.0 [-34.8, -1.4]  | -17.0 [-46.4, +17.5]  | +9.3 [+2.6, +15.4]   |
| find_one / sync / hot        | -20.8 [-29.8, -17.6] | -25.7 [-27.2, -25.2] | -4.3 [-53.1, -0.3]   | -19.2 [-44.8, -15.5]  | +17.3 [+12.2, +45.9] |
| find_one / sync / cold       | -7.6 [-11.9, -6.5]   | -4.9 [-8.0, -3.1]    | -6.7 [-26.7, +6.7]   | -2.8 [-43.4, +6.8]    | +3.8 [+2.1, +14.6]   |
| find_one / async / hot       | -23.4 [-31.6, -20.4] | -25.5 [-26.4, -24.4] | -22.3 [-52.3, -18.3] | -21.0 [-46.6, -7.6]   | +29.7 [+22.4, +49.1] |
| find_one / async / cold      | -4.1 [-7.8, -3.6]    | -3.8 [-6.2, -2.8]    | +7.9 [-10.8, +30.6]  | +6.2 [-19.8, +35.1]   | +1.9 [-2.8, +7.3]    |
| find / sync / hot            | -7.7 [-20.1, +5.4]   | -9.4 [-10.0, -6.8]   | -7.6 [-44.3, +0.4]   | -7.7 [-26.7, +1.5]    | +6.9 [-17.8, +31.2]  |
| find / sync / cold           | +0.7 [-11.0, +19.2]  | +1.6 [-4.5, +32.0]   | +6.9 [-45.1, +95.7]  | +19.9 [-55.8, +95.3]  | -2.9 [-30.4, +18.2]  |
| find / async / hot           | -6.2 [-10.0, +9.4]   | -9.5 [-11.3, -5.2]   | -4.9 [-9.9, -2.5]    | -4.6 [-8.9, -1.9]     | -2.0 [-17.9, +11.1]  |
| find / async / cold          | -3.9 [-7.6, -0.5]    | -1.6 [-5.8, +1.6]    | +5.3 [-35.4, +45.6]  | -6.3 [-45.4, +110.9]  | +2.8 [-8.0, +10.3]   |
| small-entries / sync / hot   | -34.6 [-39.2, -29.6] | -28.1 [-30.2, -27.8] | -44.0 [-51.0, -37.2] | -52.3 [-67.0, -33.3]  | +56.1 [+42.0, +68.5] |
| small-entries / sync / cold  | -5.9 [-9.4, +4.6]    | -6.5 [-7.9, +5.4]    | -3.0 [-18.4, +21.9]  | -7.5 [-26.0, +36.2]   | +4.1 [-10.6, +10.4]  |
| small-entries / async / hot  | -14.4 [-29.4, -10.3] | -28.4 [-29.3, -23.6] | +20.3 [-35.7, +55.7] | +29.7 [-27.1, +140.0] | +18.0 [+0.9, +39.8]  |
| small-entries / async / cold | -6.1 [-7.1, -0.9]    | -6.5 [-7.5, -0.3]    | -23.4 [-28.6, +17.9] | -11.9 [-33.8, +11.5]  | +7.0 [-5.1, +10.6]   |
| large-keys / sync / hot      | -14.4 [-16.5, -3.4]  | -12.8 [-14.1, -10.9] | -12.1 [-42.0, +3.6]  | -0.8 [-24.7, +6.9]    | +17.3 [-3.9, +21.2]  |
| large-keys / sync / cold     | -3.7 [-6.3, -1.2]    | -5.1 [-6.7, -3.8]    | -8.3 [-32.2, +15.2]  | -3.0 [-37.7, +11.4]   | +1.2 [-0.3, +9.4]    |
| large-keys / async / hot     | -12.9 [-16.3, -9.7]  | -12.0 [-13.5, -10.6] | -18.9 [-30.6, +8.6]  | -10.4 [-37.6, +33.7]  | +14.0 [+11.0, +19.7] |
| large-keys / async / cold    | -3.8 [-6.7, -2.3]    | -5.3 [-6.3, -3.1]    | -10.1 [-31.3, -6.9]  | -7.4 [-43.7, -0.1]    | +4.0 [+1.5, +10.5]   |

## Registered uncertainty acquisition

The one additional cohort retained C1 and repeated sorted `find` hot/cold in both
models plus async small-entry hot, with direct controls: 150 public windows.
Sorted async hot CPU improved in all N/M blocks (median −11.8%, range −14.5%
to −5.4%), with P99 median −10.3% and range −13.2% to −7.1%.
Sorted cold tails remained variable: synchronous P99 ranged −49.4% to +110.7%,
and asynchronous P99 ranged −49.1% to +16.9%. No universal tail improvement
follows from these measurements.

Async small-entry hot CPU improved in every follow-up block (median −24.1%,
range −30.2% to −19.5%). Its P99 changed by −16.6% at the median, with a
−49.5% to +36.5% range. The two cohorts do not establish a repeatable P99
regression for this cell; they also do not establish improvement in every block.
Direct controls retain the same variable-tail limitation.

### Uncertainty complete-read controls

N/M percentage changes below are medians and full ranges of paired-block
changes; individual requests are not statistical replications.

| Read / model / state        | CPU/read change      | P50 change           | P95 change           | P99 change            | Throughput change    |
| --------------------------- | -------------------- | -------------------- | -------------------- | --------------------- | -------------------- |
| find / sync / hot           | -14.4 [-26.3, +3.4]  | -9.6 [-12.2, -9.3]   | -13.4 [-45.8, +55.2] | -10.7 [-59.6, +14.9]  | +20.6 [-13.9, +30.2] |
| find / sync / cold          | -7.6 [-11.9, +1.3]   | -3.9 [-7.1, +0.1]    | -29.7 [-45.4, +66.4] | -26.7 [-49.4, +110.7] | +8.9 [-9.5, +19.6]   |
| find / async / hot          | -11.8 [-14.5, -5.4]  | -10.2 [-10.6, -9.3]  | -9.0 [-17.6, -8.3]   | -10.3 [-13.2, -7.1]   | +13.6 [+8.7, +28.1]  |
| find / async / cold         | -2.5 [-9.8, +3.6]    | -1.5 [-7.9, +0.9]    | +2.0 [-44.9, +28.6]  | +2.1 [-49.1, +16.9]   | +0.5 [-6.0, +16.5]   |
| small-entries / async / hot | -24.1 [-30.2, -19.5] | -28.8 [-29.4, -26.8] | -5.5 [-30.0, +0.7]   | -16.6 [-49.5, +36.5]  | +30.6 [+25.8, +41.8] |

## Attribution and allocation correction

Separate cProfile acquisitions cover both execution models and hot/cold generic
reads. They use elapsed time with instrumentation, not the uninstrumented CPU
acceptance clock. In the synchronous hot profiles, reference namespace lookup
had 28.44 µs/read cumulative time versus 10.33 for native lookup. Reference LRU
touch contributed 6.25 µs/read cumulative time inside lookup; these nested times
must not be summed. Key canonicalization remained Python work in both paths.
Cold native admission had 16.97 µs/read cumulative time versus 63.52 for the
reference admission path; BSON encoding and origin reads remain separate costs.
These profiles explain plausible sources of the measured gain without replacing
the complete-read result.

Allocator diagnostics identified retained attribute-name strings in native
calls. CPython's [type lookup cache](https://github.com/python/cpython/blob/v3.14.7/Objects/typeobject.c#L36-L49)
uses name identity and retains name references. Interning fixed binding names
removed that repeated allocation; its regression test failed against installed
C1 and passed against the corrected binding. The same bounded correction stores
nodes inline in existing row chunks and detaches whole arenas at close. Smoke
results and their limits remain in the plan. C2a and C2b were diagnostic
implementation snapshots within this allocation correction, not additional
qualifying cohorts. The following C2 acquisition is its sole full remeasurement.

## Corrected five-block result

The corrected cohort ran on 2026-10-28 from 02:50 to 12:03 UTC. All 15 frozen
provenance records, 600 public windows, 1,860 unique memory checkpoints, 240
complete child streams, 30 contention windows and 15 existing-test runs passed
their acquisition checks. Every component command exited successfully; the
uninstrumented acquisition logs contain no failures or warnings. The source
remained C2 throughout, and both R and N loaded the same corrected release wheel.

| Block | M µs/read | R µs/read | N µs/read | N/M CPU change | N/R CPU change | Sync PSS saving | Async PSS saving |
| ----- | --------: | --------: | --------: | -------------: | -------------: | --------------: | ---------------: |
| 0     |    24.763 |    24.120 |    18.653 |        −24.67% |        −22.67% |          2.659% |           2.652% |
| 1     |    24.571 |    24.931 |    17.107 |        −30.38% |        −31.38% |          2.662% |           2.651% |
| 2     |    24.545 |    23.613 |    22.594 |         −7.95% |         −4.31% |          2.659% |           2.656% |
| 3     |    25.971 |    23.749 |    19.897 |        −23.38% |        −16.22% |          2.657% |           2.642% |
| 4     |    25.003 |    24.778 |    17.277 |        −30.90% |        −30.27% |          2.664% |           2.638% |

CPU reduction against M has median 24.67% and range 7.95–30.90%; against R,
median 22.67% and range 4.31–31.38%. Block 2 remains valid: results, outcomes,
residency, artifacts and clock checks passed. Two native workers used about
0.423–0.425 CPU seconds while the other two used 0.311–0.322. The corresponding
median and P99 read latencies still improved, but throughput fell 2.8%. There is
no independently observed reason to invalidate the measurement for discarding this block, and
neither its better latency nor the other four blocks can replace its CPU result.
The uncertainty and correction allowances are exhausted.

Warm long-key incremental PSS is about 268.9 MiB for M/R versus 261.8 MiB for N.
The full 64,001-entry, 3,776,008-byte catalogue and 64,000 warm hits match in
both APIs with zero bypasses. Cold public controls preserve the registered
71,089-entry, 4,194,251-byte boundary and 1,104 evictions per core. Thus the limited memory
saving is not explained by retaining fewer results.

The resource correction has useful measured effects: short-filter incremental
PSS falls about 16%, and long-key retention after diagnostic trimming is lower
than main. Those checkpoints are descriptive controls, not substitute targets.
The table separates baseline-adjusted cached-minus-direct warm growth from
absolute process peaks. Peaks include import, warmup, admission and eviction.
Bytes/entry use incremental PSS divided by the observed warm entry count.

| Scenario / API        | Warm RSS MiB M→N | Warm PSS MiB M→N | Peak RSS MiB M→N | PSS bytes/entry M→N |
| --------------------- | ---------------: | ---------------: | ---------------: | ------------------: |
| documents / sync      |      66.21→66.69 |      66.21→66.65 |    122.02→123.61 |         4,959→4,991 |
| documents / async     |      66.15→66.58 |      66.24→66.62 |    122.40→123.85 |         4,961→4,990 |
| small entries / sync  |      44.84→37.68 |      44.84→37.68 |     106.46→92.18 |             735→617 |
| small entries / async |      44.80→37.64 |      44.88→37.69 |     106.73→92.31 |             735→617 |
| long keys / sync      |    268.91→261.80 |    268.91→261.76 |    357.68→343.25 |         4,406→4,289 |
| long keys / async     |    268.79→261.73 |    268.87→261.77 |    358.07→343.39 |         4,405→4,289 |

Normal close still has a repeatable synchronous long-key PSS cost. N−M is
10.635, 3.260, 8.254, 5.007 and 6.642 MiB by block; median absolute PSS is
73.48 versus 65.26 MiB. After diagnostic trimming it is 59.15 versus 65.13 MiB.
For async, normal-close medians are 87.74 versus 99.27 MiB, with mixed paired
directions; trimmed medians are 74.42 versus 99.17 MiB. These improvements
retain the normal-close regression rather than hiding it behind trimming.
Document warm PSS is also higher in every block in both APIs; its incremental
median cost is about 0.4 MiB. Repeated-cycle close PSS plateaus: fifth-cycle
medians are 46.84/46.94 MiB sync/async for N versus 48.08/47.49 for M.

Contention completes the same work and all 1,000 overlapping invalidations in
every window, with zero bypasses. For one/four readers, CPU/read changes have
medians −14.6%/−18.5% and ranges −25.6% to −11.9% / −30.6% to −7.4%.
P50 medians change −31.2%/−31.9%, P95 −25.4%/−24.7%, and P99 −7.5%/−17.7%.
P99 ranges still include increases up to 36.2%/36.4%; offered throughput stays
about 4,000/s. This establishes the registered pressure, not saturation behavior.

Existing-case wall-time medians are M 1,283.17 s, R 1,280.64 s and N 1,280.68 s;
ranges are 1,270.63–1,284.68, 1,276.83–1,288.07 and 1,273.50–1,284.51 s.
Every run has 4,366 passes and the same one real-server skip. No repeatable
existing-test slowdown is established. These durations exclude added owner/spike
tests, which were run separately for correctness.

### Complete-read controls

The table reports N/M changes. CPU lists blocks 0–4; latency and throughput show
the median and full range of paired-block relative changes. CPU/read uses the
same completed count within each cell, so its change equals total measured CPU's
change. The registered CPU target is tabulated above. Negative latency/CPU and
positive throughput changes favor N; mixed ranges retain the uncertainty.

| Read / model / state         | CPU/read N/M block changes (%)    | P50 change           | P95 change           | P99 change            | Throughput change    |
| ---------------------------- | --------------------------------- | -------------------- | -------------------- | --------------------- | -------------------- |
| identity / sync / hot        | -28.1, -26.7, -19.8, -36.4, -38.5 | -34.3 [-35.8, -29.1] | -44.0 [-65.8, -28.2] | -42.1 [-56.6, -29.2]  | +39.7 [+15.8, +72.3] |
| identity / sync / cold       | -11.8, -15.4, -7.4, -15.2, -11.7  | -8.6 [-12.6, -2.4]   | -9.5 [-35.2, +21.8]  | -4.9 [-38.0, +18.8]   | +9.9 [-3.3, +21.4]   |
| identity / async / hot       | -31.3, -39.3, -14.1, -26.1, -26.5 | -32.1 [-33.3, -26.5] | -39.6 [-57.3, -13.1] | -46.7 [-60.3, -3.9]   | +33.8 [+4.4, +58.6]  |
| identity / async / cold      | -6.2, -8.6, +0.2, -9.2, -9.3      | -7.1 [-9.6, +0.8]    | -0.3 [-22.1, +68.5]  | -4.6 [-34.4, +46.7]   | +8.9 [-11.2, +11.5]  |
| find_one / sync / cold       | -11.0, -10.4, -5.3, -11.5, -8.4   | -5.8 [-8.2, -2.9]    | -18.3 [-27.0, +18.8] | -21.6 [-23.7, +17.7]  | +10.0 [-2.2, +11.7]  |
| find_one / async / hot       | -30.2, -29.5, -19.2, -30.2, -24.5 | -29.0 [-29.2, -27.6] | -28.3 [-41.7, +15.7] | -13.5 [-29.2, +45.7]  | +40.0 [+18.3, +44.2] |
| find_one / async / cold      | -8.5, -10.0, +3.0, -8.5, -8.8     | -7.2 [-8.4, +3.3]    | -12.1 [-26.5, +68.8] | -3.2 [-25.5, +94.4]   | +7.6 [-12.6, +12.9]  |
| find / sync / hot            | +12.4, -11.8, -20.3, -9.8, -12.5  | -12.0 [-14.8, -9.4]  | -10.1 [-19.3, +38.9] | -10.7 [-15.3, +135.8] | +14.8 [-14.5, +19.1] |
| find / sync / cold           | -9.2, -8.7, -10.5, -19.2, -11.9   | -7.1 [-18.6, -3.8]   | -26.3 [-30.7, -25.2] | -19.8 [-41.0, -5.9]   | +13.8 [+8.1, +21.9]  |
| find / async / hot           | +4.1, -14.3, -3.9, -13.5, -10.8   | -11.1 [-12.8, -10.1] | -8.8 [-28.9, +40.5]  | -8.9 [-16.7, +6.6]    | +11.5 [-5.3, +22.4]  |
| find / async / cold          | -3.1, -7.4, -6.6, -5.5, -6.0      | -4.4 [-7.1, -3.8]    | -20.0 [-27.5, +38.1] | -30.0 [-51.2, +102.0] | +6.4 [-1.4, +12.6]   |
| small-entries / sync / hot   | -23.0, -31.7, -20.6, -30.4, -26.3 | -31.8 [-33.7, -31.7] | -5.5 [-31.8, -2.5]   | -35.4 [-51.0, +28.7]  | +35.3 [+18.4, +49.6] |
| small-entries / sync / cold  | -12.3, -9.7, -9.9, -10.6, -8.5    | -9.2 [-10.5, -8.4]   | -22.2 [-34.3, -1.5]  | -16.7 [-30.6, -6.3]   | +8.2 [+7.1, +13.1]   |
| small-entries / async / hot  | -12.9, -25.6, -19.5, -30.3, -31.8 | -32.0 [-33.7, -31.5] | -10.7 [-27.3, +35.1] | +5.4 [-28.6, +59.7]   | +36.8 [+15.2, +44.8] |
| small-entries / async / cold | -7.3, -8.0, -5.4, -8.7, -7.9      | -7.6 [-10.6, -6.2]   | -10.6 [-21.5, +17.8] | -8.1 [-17.4, +24.1]   | +8.3 [+1.4, +11.0]   |
| large-keys / sync / hot      | -19.9, -15.4, -10.5, -12.6, -15.9 | -15.6 [-16.2, -15.1] | -17.8 [-34.5, +0.6]  | -10.8 [-30.8, +29.3]  | +18.8 [+8.7, +26.4]  |
| large-keys / sync / cold     | -7.0, -7.0, -1.6, -8.0, -7.2      | -8.0 [-9.0, -1.5]    | -24.9 [-27.5, +27.2] | -13.8 [-23.3, +36.4]  | +8.6 [-6.5, +10.5]   |
| large-keys / async / hot     | -11.9, -11.1, -17.1, -17.4, -19.5 | -15.1 [-16.4, -13.8] | -12.5 [-27.4, -4.8]  | -20.8 [-54.7, +33.1]  | +22.4 [+12.5, +24.6] |
| large-keys / async / cold    | -4.1, -7.9, -0.4, -7.8, -5.5      | -6.8 [-8.9, -1.3]    | -10.9 [-30.2, +31.3] | -14.4 [-26.4, +27.4]  | +6.2 [-5.4, +11.3]   |

Direct controls also vary: their paired CPU changes span −11.8% to +18.1% and
P99 changes −37.5% to +121.6% across cells. This supplies context for variable
tails, without declaring unfavorable native windows invalid. The initial,
uncertainty and corrected cohorts remain separate. No further cohort is used
to search for a qualifying result.

## Reproduction and disposition

Use the published C2 checkout for the experiment commands; the delivered tree
contains the generic collectors but no native selector. The plan supplies the
M environment, frozen node-ID digest, cell matrix, orders and dependency/host
settings. Build the explicit C2 wheel from a separate checkout:

```bash
git worktree add --detach /tmp/agents/native-local-reproduction experiment/native-process-local-cache-corrected-de8408aa
cd /tmp/agents/native-local-reproduction
uv sync --locked --no-editable --group docs --config-setting build-args=--features=local-cache-prototype
CARGO_ZIGBUILD_PYTHON_PATH="$PWD/scripts/zig-linker.sh" .venv/bin/maturin build --release --zig --compatibility manylinux_2_28 --locked --features local-cache-prototype --out /tmp/agents/native-local-reproduction-wheels
uv pip install --python .venv/bin/python --no-deps --reinstall /tmp/agents/native-local-reproduction-wheels/client_query_cache-0.9.1-cp314-abi3-manylinux_2_28_x86_64.whl
source scripts/testcontainers-bridge.sh
.venv/bin/python -m research.native_process_local_cache.acquire --label N --block 0 --wheel /tmp/agents/native-local-reproduction-wheels/client_query_cache-0.9.1-cp314-abi3-manylinux_2_28_x86_64.whl --existing-nodes /tmp/agents/native-local-20261027/existing-nodes.txt --output /tmp/agents/native-local-reproduction-results/b0-N
```

Repeat the registered block orders, using M's interpreter/wheel for M and this
same corrected interpreter/wheel for R and N. Keep the C2 checkout as the working
directory for all three so collectors and test bodies match. Regenerate the
node file from M as described in the plan if the temporary original is absent;
the controller verifies its digest. Reproduce C1 with its immutable source and
feature wheel, and the uncertainty subset with U's controller and C1's wheel.
Instrumented attribution commands remain in the plan and use their named source.

The final disposition removes the native owner/spike, Python adapter/contracts,
feature exports, backend selector, prototype-only tests and orchestration. The
generic workload/value/resource collectors, accurate owner CPU clock, complete
memory-stream collection and cursor-fixture cleanup remain. The residency
protocols remain typing-only. Public cache behavior and Context7 instructions
continue to describe the reference implementation.

## Invalid runs and evidence limits

The daemon restart interrupted the initial N/block-2 supervisor. Its original
test timing was excluded and the identical node set rerun successfully; other
completed component records were retained. The initial uncertainty preparation
stopped before native follow-up execution when commit validation rejected its
registration message. It is retained separately from the completed versioned
uncertainty cohort.

An editable-build validation child loaded an extension without the experiment
feature. Subsequent installed-wheel validation avoided that source of artifact
mixing. Memory smoke runs with missing checkpoints remain invalid, including a
sequential reproduction with a missing baseline frame. The collector now rejects
such streams, preserves raw child output, and retrieves completed logs before
container removal. No missing checkpoint supports a resource claim.

An extra broad core invocation also included 135 tests that require reference
LRU/namespace internals, observer/payload construction, metadata probes or its
logger, plus 14 public reference-fault cases whose imported constructor was
incorrectly rewritten. It is retained as a failed conformance attempt, not a
native success. Restricting constructor rewriting to core-test modules fixes the
public selector; the corrected public suite passes all 665 cases, with explicit
reference-only fault hooks. Native ordering/reclamation cases exercise its own
representation as mapped in the plan.

Installed-package coverage also exposed an unused executable residency-protocol
module. It is now a typing stub, matching its exclusively static imports. The
corrected release wheel's 61 Python/stub files match frozen C2 byte for byte;
its native extension is byte-identical to the inline-node C2b extension. The
installed-wheel full gate reaches 100% Python coverage with no invalid exclusion
marks. This packaging correction does not add runtime compatibility machinery.

Memray's attribution-only run emitted two symbol-address correction warnings.
Its [documented implementation](https://github.com/bloomberg/memray/blob/v1.20.0/src/memray/_memray/hooks.h#L90-L111)
resolves the original symbol before forwarding calls. Those warnings were
investigated and retained; profiled timings do not enter qualification.
