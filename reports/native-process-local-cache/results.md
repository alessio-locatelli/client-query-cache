# Native process-local cache evaluation

The initial candidate reduced the registered complete-read CPU metric in every
block, but retained substantially more memory after cache close. It therefore
does not qualify for default integration. The single registered allocation
correction is being validated; its matched remeasurement and final disposition
are pending. No ordinary-build qualification is claimed here.

The [acquisition plan](plan.md) owns workload definitions, environment, commands,
conformance mapping, stopping conditions, and diagnostic history. Raw outputs
remain untracked under its session directory. These results concern one host
and the registered workloads, rather than an application-wide speedup.

## Immutable sources

| Identity | Source                                                                                                            | Role                                                                   |
| -------- | ----------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- |
| M        | [1f70de76](https://github.com/alessio-locatelli/client-query-cache/tree/1f70de76b6bc9fdcc4ab7cf0d4a8a4d784d9588e) | Frozen ordinary main wheel                                             |
| C1       | [a7c91530](https://github.com/alessio-locatelli/client-query-cache/tree/a7c91530bcb069dea25f0de8432cdd8f7284f66a) | Initial candidate and acquisition source; R and N use this same wheel  |
| U        | [8de2aae1](https://github.com/alessio-locatelli/client-query-cache/tree/8de2aae1d36519fd7e1996caa7cb254a64368dad) | Versioned uncertainty subset; installed runtime remains C1             |
| C2a      | [effca8d8](https://github.com/alessio-locatelli/client-query-cache/tree/effca8d862bde060dd12cf7a2cc269a7be66f04f) | Interned-name diagnostic snapshot, without a qualifying cohort         |
| C2b      | [feb0b37e](https://github.com/alessio-locatelli/client-query-cache/tree/feb0b37ed439e7c8a3258c748fc2a7e05ccb6310) | Inline-node allocation correction, before final acquisition validation |

C1's published experiment tag was retrieved into a fresh checkout and its HEAD
verified before any proposed removal. Its wheel SHA-256 is
`791528a08521fc3a1620886aa71d819caa8f4d8cb0cd97ae9775c1f7f9d991bd`.
M's wheel SHA-256 is
`85fa6e72c5526006fb051e7f96efe864b80e4d823a4716d1a700da70326128b7`.
Per-revision provenance records retain imported paths, extension digests,
dependencies, clocks, and limits. Source URLs alone are not build hashes.

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
results and their limits remain in the plan pending the matched corrected cohort.

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

Installed-package coverage also exposed an unused executable residency-protocol
module. It is now a typing stub, matching its exclusively static imports. The
corrected release wheel's 61 Python/stub files match the source byte for byte;
its native extension is byte-identical to the inline-node C2b extension. The
installed-wheel full gate reaches 100% Python coverage with no invalid exclusion
marks. This packaging correction does not add runtime compatibility machinery.

Memray's attribution-only run emitted two symbol-address correction warnings.
Its [documented implementation](https://github.com/bloomberg/memray/blob/v1.20.0/src/memray/_memray/hooks.h#L90-L111)
resolves the original symbol before forwarding calls. Those warnings were
investigated and retained; profiled timings do not enter qualification.
