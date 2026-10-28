# Native process-local cache evaluation

The ordinary wheel uses the Rust process-local owner in both APIs. Its registered complete hot `find_one()` CPU target improves in all five matched blocks: median 25.4%, range 11.3–31.5% against frozen main. The revised acceptance rule requires a demonstrated stable benefit, without a minimum percentage. Resource costs and inconclusive controls remain visible below.

## Historical candidate disposition

Under the original registered stopping rule, the prototype was rejected despite a 24.7% median corrected complete-read CPU reduction: one valid block improved only 7.95%, below its 10% cutoff. Long-key incremental warm PSS fell about 2.7%, below the alternative 20% cutoff. The correction substantially improved allocation lifetime, while synchronous long-key memory after normal close remained higher than main in every block.

That earlier disposition removed experimental runtime code and preserved the measured native implementation, tests, and selection tools in published history. It did not acquire an ordinary-native final wheel. The revised policy changes the adoption decision; it does not change those original measurements or their preregistered cutoffs.

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

## Historical candidate reproduction and disposition

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

The earlier negative disposition removed the native owner/spike, adapter/contracts, feature exports, selector, tests and orchestration while retaining the generic collectors. Ordinary-wheel adoption below restores the corrected owner through normal construction, with ownership tests in the regular suite and no selection hook. Documented public read and inspection behavior remains unchanged.

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

## Ordinary-wheel acquisition setup rejection

The first final-wheel baseline acquisition stopped at the first shared warm control: the new pre-warm metadata probe returned the legitimate transient `stream-starting` state. No native timing ran. Its two completed baseline windows and the failed setup remain under `/tmp/agents/native-local-20261027/final-cohort-setup-rejection`; they have no paired final-wheel comparison and do not enter the adoption decision. The collector now waits for that observed transient state within its existing readiness deadline, includes that wait in startup cost, and exposes worker failures while aborting peer barriers. The workload, target, and acceptance rule are unchanged.

## Ordinary-wheel adoption

The runtime is frozen at `cd9967d0592edc06568748c081926a3136b1c6fd`; the final acquisition harness is `34cb5fa4187a9c7ad22ea6aab1a99d02ec16278c`. F is an ordinary release wheel with no prototype Cargo feature or constructor selection. Its SHA-256 is `75cdc05312c975613ae2883b4ae61386219378dbe6072e194558a5dc6b25c6a0`; all 61 packaged Python/stub files matched the frozen source. M uses the original wheel identified above. Installed dependency versions matched exactly.

The five blocks follow the original change's D6 registration. They contain 460 public windows, 1,240 complete memory checkpoints and 20 contention windows. Every completed performance component passed its result, installed-path, residency, cache-outcome and origin-read checks. All ten performance-component provenance records identify the frozen harness above; the subsequent test-source-overlay correction is recorded by the test command metadata. Raw outputs remain under `/tmp/agents/native-local-20261027/final-cohort`.

### CPU confirmation and complete-read controls

The predeclared target is synchronous generic `find_one()` hot CPU/read with four independent managers, including reader supervision. Each row is one paired block, not an independent request sample. All five favor F (one-sided exact sign test, p = 1/32), confirming the target direction under the registered rule.

| Block | M CPU µs/read | F CPU µs/read | F/M change |
| ----- | ------------: | ------------: | ---------: |
| 0     |        24.472 |        21.713 |    -11.27% |
| 1     |        27.761 |        21.946 |    -20.95% |
| 2     |        31.943 |        21.887 |    -31.48% |
| 3     |        27.724 |        20.687 |    -25.38% |
| 4     |        30.432 |        22.087 |    -27.42% |

The following independent-manager controls report median [minimum, maximum] paired changes in percent; negative CPU/latency and positive throughput changes favor F. They are workload-specific observations rather than an application-wide speedup. Direct controls remain part of the acquisition and retain variable tails.

| Read / API / temperature     | CPU/read %           | P50 %                | P95 %                | P99 %                | Throughput %          |
| ---------------------------- | -------------------- | -------------------- | -------------------- | -------------------- | --------------------- |
| identity / sync / hot        | -35.1 [-61.9, -16.6] | -34.1 [-72.2, +3.0]  | -43.0 [-45.9, -19.8] | -43.2 [-48.6, -20.5] | +58.5 [+18.8, +117.0] |
| identity / sync / cold       | -11.7 [-14.7, -10.2] | -7.6 [-10.9, -6.5]   | -4.4 [-27.9, +2.0]   | -3.9 [-40.3, +1.6]   | +8.0 [+5.8, +19.4]    |
| identity / async / hot       | -40.2 [-46.2, -9.5]  | -32.4 [-34.0, -28.2] | -42.2 [-45.6, -11.5] | -42.4 [-44.2, -6.4]  | +59.3 [+18.4, +118.5] |
| identity / async / cold      | -8.5 [-10.5, -5.9]   | -7.1 [-10.4, -3.7]   | -2.7 [-13.7, +19.4]  | -4.0 [-15.3, +8.3]   | +7.3 [-1.2, +10.5]    |
| find_one / sync / hot        | -25.4 [-31.5, -11.3] | -30.4 [-30.7, -29.2] | -23.6 [-23.9, +6.4]  | -23.2 [-23.9, -19.6] | +34.5 [-4.5, +43.6]   |
| find_one / sync / cold       | -9.3 [-10.4, -8.8]   | -6.3 [-7.2, -1.8]    | -8.8 [-23.7, +5.9]   | -8.3 [-30.4, +4.7]   | +8.4 [+0.2, +13.6]    |
| find_one / async / hot       | -28.9 [-40.3, -15.1] | -28.9 [-56.3, -28.8] | -23.1 [-42.7, +2.4]  | -22.9 [-38.6, -0.4]  | +41.2 [+17.6, +57.3]  |
| find_one / async / cold      | -7.9 [-8.6, -4.7]    | -6.2 [-6.7, -3.3]    | -2.6 [-17.4, +20.6]  | -2.7 [-22.3, +27.6]  | +5.4 [-5.5, +10.9]    |
| find / sync / hot            | -14.2 [-27.0, +0.8]  | -11.5 [-51.0, -10.1] | -10.3 [-17.5, -6.4]  | -11.7 [-16.3, -4.7]  | +8.6 [-1.3, +30.5]    |
| find / sync / cold           | -5.2 [-9.5, -4.6]    | -4.8 [-5.9, -1.6]    | +5.6 [-25.2, +16.2]  | +9.8 [-57.9, +41.2]  | +1.8 [+0.3, +10.4]    |
| find / async / hot           | -3.4 [-16.6, +34.4]  | -10.6 [-39.6, +67.9] | -7.7 [-11.4, +7.8]   | -8.1 [-13.2, +6.7]   | +4.6 [-13.4, +27.6]   |
| find / async / cold          | -3.9 [-10.4, -1.8]   | -3.1 [-9.8, +0.5]    | +12.7 [-36.7, +32.5] | +28.4 [-50.0, +62.8] | -1.5 [-3.5, +17.0]    |
| small-entries / sync / hot   | -29.0 [-36.4, -15.7] | -31.0 [-32.5, -28.7] | -35.9 [-37.5, -5.4]  | -35.5 [-37.7, -8.7]  | +38.7 [+23.5, +60.8]  |
| small-entries / sync / cold  | -8.8 [-10.1, -7.1]   | -8.0 [-12.9, -6.7]   | +9.0 [-23.7, +17.1]  | +6.5 [-25.9, +34.5]  | +5.2 [+1.5, +10.0]    |
| small-entries / async / hot  | -32.3 [-47.3, -28.4] | -33.4 [-58.0, -30.1] | -34.5 [-54.5, -34.2] | -34.1 [-52.6, -32.8] | +51.8 [+35.0, +93.9]  |
| small-entries / async / cold | -7.3 [-7.8, -6.1]    | -7.1 [-8.0, -6.1]    | -9.8 [-11.4, +8.0]   | -14.2 [-18.5, +9.3]  | +6.3 [+3.6, +8.1]     |
| large-keys / sync / hot      | -13.6 [-21.0, -11.9] | -15.9 [-16.9, -15.4] | -12.2 [-13.1, -11.6] | -11.9 [-12.7, -11.3] | +18.8 [+15.5, +19.5]  |
| large-keys / sync / cold     | -4.4 [-5.6, -3.8]    | -5.8 [-6.6, -5.4]    | -9.0 [-17.0, +2.3]   | -1.9 [-16.6, +8.2]   | +2.9 [+1.2, +6.0]     |
| large-keys / async / hot     | -17.2 [-24.0, -14.2] | -15.5 [-15.9, -13.5] | -12.2 [-25.6, -11.0] | -11.9 [-22.4, -11.0] | +16.4 [+14.2, +33.8]  |
| large-keys / async / cold    | -4.2 [-5.9, -1.6]    | -5.3 [-6.3, -1.1]    | +2.7 [-18.7, +13.4]  | +2.2 [-30.4, +20.6]  | +2.0 [-5.0, +7.8]     |

### Resource controls and accepted costs

Warm RSS/PSS and bytes/entry below use baseline-adjusted cached-minus-direct growth. Peak RSS is the median of each process's maximum across measured lifecycle phases; close/trimmed PSS is absolute. Equal warm entry counts and BSON weights match in M and F. The small/long-key checkpoints retain 64,001 entries and 3,776,008 BSON bytes, with zero bypasses; their public cold trajectories retain the registered 71,089-entry, 4,194,251-byte boundary and 1,104 evictions.

| Scenario / API        | Warm RSS MiB M→F | Warm PSS MiB M→F | Peak RSS MiB M→F | PSS bytes/entry M→F | Close PSS MiB M→F | Trimmed PSS MiB M→F |
| --------------------- | ---------------: | ---------------: | ---------------: | ------------------: | ----------------: | ------------------: |
| documents / sync      |      66.21→66.68 |      66.21→66.63 |    122.11→123.37 |         4,959→4,990 |     106.71→104.50 |         42.26→41.39 |
| documents / async     |      66.15→66.58 |      66.23→66.62 |    122.61→123.89 |         4,960→4,990 |      54.84→104.57 |         43.09→41.50 |
| small-entries / sync  |      44.84→37.66 |      44.84→37.66 |     106.70→92.15 |             735→617 |       60.02→51.33 |         52.96→49.95 |
| small-entries / async |      44.74→37.63 |      44.83→37.67 |     107.05→92.45 |             734→617 |       69.82→57.67 |         62.79→56.31 |
| large-keys / sync     |    268.90→261.80 |    268.90→261.76 |    357.18→343.34 |         4,406→4,289 |       69.97→70.30 |         69.83→55.91 |
| large-keys / async    |    268.84→261.73 |    268.92→261.77 |    357.89→343.41 |         4,406→4,289 |       92.64→84.95 |         92.49→71.60 |

Small-result incremental PSS falls about 16%; long-key growth falls about 2.7%. Document residency costs about 0.4 MiB more, consistent with the corrected candidate. Synchronous long-key ordinary-close paired PSS differences are mixed (−0.81 to +5.86 MiB, median +2.71 MiB), while trimming releases additional allocator-held memory. The user accepted the corrected candidate's previously documented residency/close costs as nonmaterial for adoption; the library does not call `malloc_trim()`.

Document close is allocator-sensitive: F ends near 104–105 MiB, while M ranges about 43–109 MiB. Thus some paired closes retain roughly 60 MiB more than M, and others retain less. The same bimodal M behavior and approximately 104 MiB native close footprint occur in the preserved C2 data; this is not a new ordinary-build change or proof of a leak. After diagnostic trimming, both return to about 41–43 MiB. Repeated-cycle fifth-close medians are F 46.98/46.81 MiB versus M 48.04/48.19 MiB for sync/async, with a plateau rather than unbounded growth. These observations preserve the unfavorable close cases and establish no RSS ceiling.

### Shared-cache and startup controls

Shared warm read changes use the same median [minimum, maximum] convention. Mixed CPU, latency and throughput directions remain inconclusive: these windows do not prove absence of a smaller shared regression. Stable group-PSS increases for filtered reads are below 0.9 MiB across the owner plus four workers; the fixed combined-binary/type cost is nonmaterial alongside this topology's roughly 70 MiB per-worker RSS and existing mapped-cache budget.

| Shared read / API | CPU/read %          | P50 %                | P95 %               | P99 %               | Throughput %        | Warm group PSS delta KiB |
| ----------------- | ------------------- | -------------------- | ------------------- | ------------------- | ------------------- | ------------------------ |
| identity / sync   | +6.6 [-22.6, +15.6] | +10.0 [-37.5, +58.5] | +2.5 [-9.7, +3.1]   | +8.6 [-21.1, +16.5] | -9.0 [-17.1, +10.4] | -129.0 [-288.0, +415.0]  |
| identity / async  | +2.5 [-22.6, +16.1] | -0.4 [-32.7, +26.0]  | +1.4 [-10.3, +12.1] | +2.9 [-14.3, +29.2] | -2.4 [-13.3, +37.7] | -366.0 [-572.0, +442.0]  |
| find_one / sync   | -3.0 [-10.9, +4.4]  | -2.0 [-11.8, +0.4]   | -4.8 [-22.1, +0.0]  | -5.3 [-19.5, +0.2]  | +2.1 [-13.3, +8.9]  | +133.0 [+69.0, +247.0]   |
| find_one / async  | +1.0 [-16.6, +23.2] | +0.8 [-2.9, +4.4]    | +0.6 [-19.3, +28.5] | +0.7 [-19.7, +27.5] | -2.3 [-19.2, +23.2] | +157.0 [+68.0, +324.0]   |
| find / sync       | -1.2 [-3.5, +22.0]  | +0.1 [-17.2, +6.8]   | -0.6 [-1.3, +22.5]  | -1.2 [-4.4, +19.2]  | +2.4 [-12.2, +4.5]  | +602.0 [+115.0, +868.0]  |
| find / async      | -0.4 [-20.6, +3.9]  | -11.0 [-44.6, +3.6]  | -0.9 [-1.5, +9.8]   | -0.9 [-3.9, +7.0]   | +2.8 [-1.1, +16.6]  | +280.0 [+274.0, +492.0]  |

The next table separates attachment/metadata readiness before result warmup from the stable warm resource sample. Startup group CPU counts the owner and workers; supervisor CPU remains separate in raw output. Worker RSS is measured after complete warmup; owner RSS here is measured before warmup.

| Shared read / API | Pre-warm wall ms M→F | Pre-warm group CPU ms M→F | Pre-warm group PSS delta KiB | Worker RSS MiB M→F | Owner RSS MiB M→F |
| ----------------- | -------------------: | ------------------------: | ---------------------------- | -----------------: | ----------------: |
| identity / sync   |          526.0→523.8 |             1253.7→1260.9 | +269.0 [-208.0, +499.0]      |        70.32→70.31 |       61.89→62.05 |
| identity / async  |          516.1→520.8 |             1260.8→1240.8 | +87.0 [-277.0, +738.0]       |        70.72→70.86 |       61.89→61.99 |
| find_one / sync   |          512.5→505.6 |             1242.3→1166.6 | +41.0 [+20.0, +289.0]        |        71.09→71.20 |       62.03→62.19 |
| find_one / async  |          521.6→524.7 |             1257.5→1276.0 | +204.0 [+23.0, +528.0]       |        71.44→71.56 |       61.84→62.16 |
| find / sync       |          522.7→517.1 |             1261.4→1259.6 | +720.0 [+83.0, +867.0]       |        72.30→72.47 |       62.07→62.16 |
| find / async      |          519.5→510.7 |             1245.1→1236.0 | +366.0 [+305.0, +609.0]      |        72.76→72.91 |       61.89→62.12 |

Fresh-process library/PyMongo import takes roughly 83–98 ms across controls, with mixed paired directions. Empty client/manager setup costs roughly 1.5–2.5 ms after import. F adds about 0.1 ms CPU and 0.2 MiB PSS to that first setup; these fixed process-start costs are amortized by normal manager reuse and do not offset the repeated-read benefit. No backend/toolchain installation change is required.

### Contention, conformance and test execution

Each one/four-thread window completes 80,000 reads at the offered 4,000 reads/s and processes 1,000 invalidations with zero bypasses. Actual call-interval overlap counts are 12–27 for M and 10–23 for F; enclosing-window application counts are not substituted for call-level overlap. Median CPU/read changes are −19.7%/−17.8%; ranges are −31.9% to +0.3% / −21.1% to −13.8%. P99 changes range −17.2% to −12.0% / −14.3% to −8.2%. Offered throughput is a load control, not a saturation claim.

The ordinary installed F wheel passes 1,145 public/ownership conformance cases. The full Python suite reaches 100% line/branch coverage and passes strict exclusion checks. One earlier run's incomplete child coverage database is tracked separately in [issue #354](https://github.com/alessio-locatelli/client-query-cache/issues/354); the subsequent complete rerun emitted no warnings.

Existing-case timing is recorded after the setup recoveries below; added ownership/race tests are excluded from its frozen node selection. Four startup-harness cases require checkout source paths. For timing only, M's 59 and F's 61 source Python/stub files were byte-verified against their installed wheels, and the exact wheel extensions were placed in their source packages. Child `PYTHONPATH` selects the matching checkout; all 4,367 registered tests remain selected. Installed-wheel conformance and performance acquisitions remain separate. The complete matched pair records 4,366 passes and one identical real-server skip for each revision: wall time M 330.545 s versus F 327.353 s, child CPU M 400.337 s versus F 393.252 s. One pair is a regression control, not evidence of a stable test-speed improvement.

### Runtime-capacity rejection and reproducibility

The first existing-test M attempt exhausted Podman's 2,048 resource locks while creating temporary volumes (13 failures and 874 setup errors). Its 71.4-second duration is invalid test-timing evidence. It remains in `final-cohort/b5-M-runtime-capacity-rejection`; all ten previously completed performance components remain valid. Recovery backed up and removed only 321 verified-empty, unused anonymous volumes created during this campaign, leaving older volumes and host settings untouched. Measured-container teardown now removes its own anonymous volumes; two lifecycle probes verified that cleanup. Recovery backups/metadata remain in `/tmp/agents/native-local-20261027/empty-volume-recovery`.

The first post-recovery M test run completed 4,362 passes and one skip but failed the four source-location assertions described above; its duration is also excluded and retained in `b5-M-installed-path-rejection`. A source-overlay preflight was aborted when verification caught an omitted subprocess environment argument (`b5-M-source-overlay-preflight-abort`); no timing from that attempt is accepted. Both wheels then passed all four affected source-harness cases through the corrected child invocation before the complete matched pair restarted. No case was dropped to obtain a passing timing.

Build F normally, install its wheel into a separate environment, and use the existing generic collectors through the committed acquisition module. The frozen baseline/node regeneration and dependency/host setup remain in the original plan. For each registered M/F block, run from the integrated harness checkout, selecting its installed interpreter and wheel:

```bash
CARGO_ZIGBUILD_PYTHON_PATH="$PWD/scripts/zig-linker.sh" .venv/bin/maturin build --release --zig --compatibility manylinux_2_28 --locked --out /tmp/agents/native-local-final-wheels
source scripts/testcontainers-bridge.sh
<installed-python> -m research.native_local_integration.acquire --label <M-or-F> --block <0-through-4> --wheel <absolute-wheel-path> --existing-nodes <absolute-frozen-node-file> --output <new-absolute-output-directory> --components public memory contention
<installed-python> -m research.native_local_integration.acquire --label <M-or-F> --block 5 --wheel <absolute-wheel-path> --existing-nodes <absolute-frozen-node-file> --output <new-absolute-output-directory> --test-checkout <matching-revision-checkout> --components tests
```

Use M/F, F/M, M/F, F/M, M/F order. M's test checkout is frozen main; F's is the integrated checkout. The newly added namespace-clear case is deselected from timing. Before test timing, verify each source package against its wheel and extract that wheel's native extension into the matching source package; `--test-checkout` sets the child source overlay required by the source-harness tests. Current post-record container cleanup prevents the anonymous-volume accumulation without changing the recorded workload or resource checkpoints. The normal core is retained in this branch; experimental source tags remain reproducible historical evidence.
