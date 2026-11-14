# Shared find preparation and rejected selection designs

The October 26, 2026 investigation of [#341](https://github.com/alessio-locatelli/client-query-cache/issues/341)
identified duplicate query serialization on shared find misses. The retained
correction encodes the query family once for both local lookup and owner
selection. Current protocol and memory details belong in the
[shared implementation guide](../../../docs/development/shared-cache.md).

## Conditions

Baseline was installed release 0.9.1 at
`71dcbf790686b76dc97a72193a94ec63260af804`. CPython 3.14.7, PyMongo 4.18.2,
psutil 7.2.2, Rust 1.99.1, Intel i3-13100, Fedora 44 Toolbx, Linux 7.2.11
and glibc 2.43; isolated MongoDB 9.0.4 had two CPUs and 1 GiB.
Four spawned workers each issued one serial majority read at a time.
Identity cells warmed 1,024 keys; sorted cells warmed 128 groups of sixteen
4,096-byte-payload documents. Three alternating revision pairs rotated API order.

Shared storage used a 32 MiB budget, 40 MiB arena and 16,384 slots; independent
managers had 64 MiB each. Hot catalogues fit both. Cold sorted results exceeded
the shared budget, so lower shared PSS there was not equal-residency savings.
Worker-plus-owner CPU covered the measured read interval, excluding MongoDB,
initialization and admission work after the finish barrier. Peak memory was
not measured. These closed-loop cells do not estimate fixed-demand deployment cost.

## Rejected alternatives

| Design                                                                | Measured benefit                                                          | Reason for rejection                                                                                                                        |
| --------------------------------------------------------------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Native family directory at `a04f47246c11e61b5094da7b3ad24591801c8fa3` | Cold sorted P50 fell 17.9–22.3% sync, 27.1–34.9% async across three pairs | Sorted group PSS rose 4.41–6.44 MiB; publication/removal cost about 2.0–2.4× baseline.                                                      |
| Counting family filter at `a403bc50eed94a99566d91b0f14340b4803027f3`  | Removed most selection RPCs without directory allocations                 | Sync identity cold P99 increased in all nine final/control pairs, including six additional controls (0.5–74.3%); cause remained unisolated. |

The filter's definite-miss shortcut weakened with occupancy: at 4,096 slots,
4,096 absent-family probes produced 0%, 0.44%, 5.22% and 41.67% owner fallbacks
with 1, 128, 512 and 2,048 resident families. These are isolated observations,
not universal collision rates. Removing selection exchanges did not remove
result transport: a larger local-capture envelope slightly increased sent bytes.
Reconsidering either design requires complete-path and maintenance costs.

## Retained paired-key encoder

Final correction `61d0ab56105a81174a6a93e9ef7ab2ed512b5e8f` preserved owner
selection. Five alternating 10,000-query batches measured 25.63 µs/query baseline
(range 24.82–26.44) versus 6.47 (6.18–6.95), about 75% less preparation CPU.
Canonical families were built outside timing; distinct keys avoided retained-key
hits, and wire-byte equality was checked separately. This is an encoding floor,
not a 75% database-latency improvement.

Earlier final-allocation source `5913ef1ef6c39d76a98adf74e7dc413fdc1b5c99`
provided the complete sorted comparison: sync cold P50 fell 8.0–14.8% in every
pair. Async cold P95 and hot throughput had unfavorable uniform directions in
that small cohort, with overlapping ranges and mixed signals in preceding
cohorts. Sorted group PSS rose 0.12–0.49 MiB, up to 0.23%. The accepted trade-off
was reduced preparation CPU with that memory cost and unresolved async effects.
The later limit-type fix was timed only for preparation; it does not requalify
the earlier end-to-end data.

Eager encoder initialization added work to processes that never encoded a find;
lazy construction removed it. The private cache also distinguishes BSON `Int64`
limits from equal plain integers, because their wire encodings differ. Python
dictionary equality alone cannot establish wire identity. Native key preparation
later superseded the Python-core costs, but these constraints survive.

## Reproduce

Use each named source's installed release wheel with one collector and matched
locked dependencies. The [historical baseline commands](https://github.com/alessio-locatelli/client-query-cache/blob/243cbfb790766e9ee25b3ecced1ffe83e96d083c/reports/shared-worker-cache/current-costs/results.md#reproduce)
and [native-trial commands](https://github.com/alessio-locatelli/client-query-cache/blob/243cbfb790766e9ee25b3ecced1ffe83e96d083c/reports/shared-worker-cache/current-costs/native-trials.md#reproduce-the-native-trials)
identify the native-floor/saturation harnesses. For the isolated
separate-versus-paired encoding comparison, use the
[frozen collector](https://github.com/alessio-locatelli/client-query-cache/blob/ca66cf58ec3618445f7504d83a35fdf706b657e9/research/shared_find_misses/floors.py)
with the named installed versions.
Separate profiles from timing. Raw outputs remain untracked; summaries cannot
recover historical sample distributions.
