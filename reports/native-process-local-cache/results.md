# Native process-local owner evaluation

This October 2026 comparison supports retaining native entry metadata while
preserving Python key references. The normal package uses the native owner;
the former Python engine and private prototype selectors are removed.

## Ordinary-wheel adoption

Baseline M was `1f70de76b6bc9fdcc4ab7cf0d4a8a4d784d9588e`; ordinary native F
was `cd9967d0592edc06568748c081926a3136b1c6fd`. Harness
`34cb5fa4187a9c7ad22ea6aab1a99d02ec16278c` ran five paired blocks in
M/F, F/M, M/F, F/M, M/F order. Installed release wheels used matching locked
dependencies: CPython 3.14.7, PyMongo 4.18.2, Intel i3-13100, Fedora Toolbx,
glibc 2.43 and disposable MongoDB 9.0.4 (two CPUs, 1 GiB for public cells).

Four spawned workers each read the same 1,024-key catalogue of 4,096-byte
payloads, 16,384 hot generic `find_one` samples per worker. CPU includes reader
supervision and excludes MongoDB. Each row is one complete paired block:

| Block | M CPU µs/read | F CPU µs/read | F/M change |
| ----- | ------------: | ------------: | ---------: |
| 0     |        24.472 |        21.713 |    -11.27% |
| 1     |        27.761 |        21.946 |    -20.95% |
| 2     |        31.943 |        21.887 |    -31.48% |
| 3     |        27.724 |        20.687 |    -25.38% |
| 4     |        30.432 |        22.087 |    -27.42% |

All five target blocks favor F (one-sided sign test p=1/32); median CPU reduction
was 25.4%, with 11.3–31.5% range. Other shapes and shared hot controls had mixed
tail/CPU directions. This establishes a benefit for the target workload, not
an application-wide speedup or absence of smaller shared regressions. Shared
filtered-read group PSS increases were below 0.9 MiB across owner plus four
workers. Import took about 83–98 ms; first empty manager setup added roughly
0.1 ms CPU and 0.2 MiB PSS with F.

The [memory report](../process-memory/summary.md#native-core-residency) retains
equal-residency and allocator-close costs. Offered-load contention cells used
one/four threads, 80,000 reads at 4,000/s and 1,000 invalidations per window;
median CPU changes were −19.7%/−17.8%, with mixed one-thread CPU directions.
Equal offered throughput does not establish saturation capacity.

## Representation and allocation constraints

An opaque Python key can recognize an existing canonical tuple by identity.
Reconstructing compact native tuple nodes failed mixed opaque/scalar equality
in one lookup order. The selected representation keeps original Python key
references and native metadata. Equality callbacks and reference destruction
must run outside the core mutex, with version revalidation before committing.
The current [core verification guide](../../docs/development/architecture.md#core-verification)
owns those invariants and tests.

An initial prototype retained attribute-name strings created repeatedly by
native binding calls. CPython's [type lookup cache](https://github.com/python/cpython/blob/v3.14.7/Objects/typeobject.c#L36-L49)
retains name references; interning fixed binding names removed that allocation
source. Inline nodes and whole-arena release also reduced post-close retention.
Zero resident entries alone had not established absence of allocator retention.

## Reproduce

Use the named M/F sources and harness with separate installed-wheel environments,
matching dependencies and the same public/memory/contention cells. The
[frozen acquisition protocol](https://github.com/alessio-locatelli/client-query-cache/blob/243cbfb790766e9ee25b3ecced1ffe83e96d083c/reports/native-process-local-cache/plan.md#registered-cells-and-ordering)
specifies populations and ordering; the
[ordinary-wheel commands](https://github.com/alessio-locatelli/client-query-cache/blob/243cbfb790766e9ee25b3ecced1ffe83e96d083c/reports/native-process-local-cache/results.md#runtime-capacity-rejection-and-reproducibility)
specify wheel installation and collector invocation. Prototype commands there
require their published experimental source, not the current package.

Raw samples are untracked. These measurements predate subsequent native key
preparation, capture and telemetry changes; they explain the representation
choice and resource trade-offs rather than provide a current latency baseline.
