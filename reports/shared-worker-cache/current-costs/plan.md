# Current shared-cache cost investigation

This bounded investigation addresses [issue #341](https://github.com/alessio-locatelli/client-query-cache/issues/341).
The plan is recorded before acquisition. It measures the public API at release
`71dcbf790686b76dc97a72193a94ec63260af804` (0.9.1), using
[`benchmarks.public_shared_cache`](../../../benchmarks/public_shared_cache.py).
Historical [identity](../v15/results.md), [sorted-find](../sorted-find/results.md)
and [collection-read](../collection-reads.md) results motivate the questions;
their measurements are not current baselines.

## Questions and hypotheses

1. Exact integer `_id` hits can use the mapped index without a synchronous owner
   round trip. Check whether their current latency and reader CPU differ from
   independent caches, and whether a small catalogue amortizes owner memory.
2. Sorted `find().sort().limit(16).to_list()` hits also have local publication,
   but construct query keys, cursors and decoded documents. Determine whether
   hot-read cost comes from that application work or shared coordination.
3. Cold shared reads additionally capture and publish results. Compare their
   incremental latency and CPU with both direct reads and independent admission;
   use separate profiles to identify any repeated work or IPC boundary worth
   changing.

## Acquisition

Use one freshly built, installed release wheel from the clean release source,
CPython 3.14.7 and the committed dependency lock. Keep builds, tests and other
benchmark campaigns stopped during measurement. Record the native digest,
dependency versions, host, MongoDB image and configuration with the results.
Do not use an editable or instrumented native build.

Use four spawned workers, one serial read at a time per worker, on the same host
and disposable pinned MongoDB replica set (two CPUs, 1 GiB). Every document has a
4,096-byte payload. All paths use majority reads and consume the same result.

| Query                       | Warm catalogue | Hot calls per worker | Cold calls per worker |
| --------------------------- | -------------: | -------------------: | --------------------: |
| Exact `_id`, one document   |     1,024 keys |                8,192 |                 1,024 |
| Sorted `find`, 16 documents |     128 groups |                1,024 |                   256 |

For each query/workload, run three repetitions in both sync and asyncio models.
Rotate direct, independent and shared path order by repetition, as the harness
does already: 72 uninstrumented windows in total. Workers warm the same
catalogue; cold measured keys are disjoint from it and from each other. Retain
every completed window. Require all hot cached reads to hit, all cold cached
reads to miss, and zero bypasses before interpreting a comparison.

These are closed-loop observations, not fixed-demand capacity qualification or
a repeat of the historical promotion protocol. Report window P50/P95/P99,
completed reads/second, worker-plus-owner CPU/read and group PSS, with MongoDB
CPU separately. Group PSS sums workers and owner while their mappings remain
alive; it excludes MongoDB, the parent collector and seeding. Reader CPU excludes
initialization, warmup and shutdown. The harness does not provide peak PSS,
collector CPU or MongoDB memory, so do not infer total deployment savings.
Keep raw samples and profiles untracked.

## Attribution, alternatives and stopping rules

After timing, collect at most 16 separate worker-profile windows: both queries,
both models, hot/cold, independent/shared, one repetition and 256 calls per
worker. Profile times explain call paths only; never mix them into latency
tables. Inspect all worker IDs and distinguish cumulative from exclusive CPU.
Inspect source and owner counters where profiles indicate IPC; add at most four
untimed diagnostic windows to attribute owner selection/publication traffic.

Use medians and full ranges of the three window statistics; requests within a
window are not independent repetitions. Treat overlapping ranges or mixed
paired directions as uncertain. For a specific uncertain comparison, allow at
most 12 additional uninstrumented control windows, declaring the question and
schedule before running them. Stop at that cap and retain uncertainty.

Compare concrete alternatives at the responsible boundary: direct reads,
independent ownership, the current mapped local-hit/shared-owner design, and,
if attribution warrants it, a different ownership/protocol or Python/Rust split.
Account for latency, CPU, memory, failure fencing, codec/result semantics and
stream ownership together. A small cost alone does not justify retaining
redundant work. Conversely, a slower cold cache path alone does not establish
that its consistency work is avoidable.

A runtime change requires an identified removable operation, a correctness
argument and a measured alternative; consequential options require user design
approval and OpenSpec before implementation. Any approved implementation stays
under #341 through matched main/candidate measurement and validation. If the
bounded evidence supports no runtime change, publish that decision and its
limits without inventing a performance guarantee or an untracked follow-up.
