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

## Native find implementation comparison

The initial acquisition identified cold sorted-find selection as a repeatable
cost. The user selected a native find miss design over key reuse within the
existing protocol. The resulting OpenSpec change is
`native-shared-find-misses`; its detailed design requires approval before
implementation. This extension is registered before candidate acquisition.

Use the original identity and sorted workloads with shared paths only, comparing
clean main and candidate installed release builds. Three alternating revision
pairs, both models and hot/cold make 48 windows. Reverse revision order in the
second pair and rotate the starting model between pairs. Retain the initial
direct/independent measurements as workload controls, without treating their
older windows as candidate comparisons. This is a scoped implementation check,
not general capacity or historical confidence-bound qualification.

For this comparison the collector seeds only the warm catalogue in hot windows,
avoiding the unread cold keys seeded by the discovery collector. Apply this
setup change identically to main and candidate. The timed hot query population
is unchanged and must remain all hits.
Record worker owner-request counts in every window to distinguish local hits
from owner-served hits; diagnostic windows additionally retain transport bytes.

Before integration, measure native exact hits, compatible hits, misses and
publication/removal at 1, 8 and 64 limits per family in five alternating batches
per build, using 4 KiB encoded payloads and 10,000 operations per read batch.
Keep setup outside timing and measure mutation batches separately. Reject an
approach whose exact-hit cost or maintenance scaling shows a reproducible
regression; a beneficial cold-read median cannot excuse it.

Use the four diagnostic-window allowance for current and candidate sorted cold
reads in both models. Record worker/owner CPU separately, selection and admission
counts, IPC bytes and publication refusals through existing counters. A separate
small-capacity correctness diagnostic must retain owner reuse when either entry
or directory publication fails, and must show bounded metadata after release.
These instrumented observations are excluded from timing tables.

Acceptance requires expected cache outcomes, no correctness failure, reduced
cold sorted selection work, and no reproducible regression in latency, reader
CPU, memory, affected identity reads or existing-test duration. Use the same
median/range uncertainty rules and at most 12 additional timing windows for one
declared unresolved comparison. If a design fails, retain that result and seek
approval for a consequential replacement rather than expanding indefinitely.

### Registered identity-tail control

The first three implementation pairs show higher candidate asyncio identity
cold P99 in all pairs, with overlapping ranges and mixed reader-CPU directions.
Use the twelve-window allowance only for this question: six more main/candidate
pairs of the unchanged asyncio identity cold workload (1,024 calls per worker,
1,024 warm keys, shared only). Alternate main/candidate order in odd pairs and
candidate/main in even pairs. Run after test timings finish; do not run builds
or tests concurrently. Retain all twelve windows and stop there, reporting
uncertainty if the combined results do not establish a repeatable difference.

### Approved replacement after rejected resource costs

The directory candidate is retained as rejected evidence. The user approved the
counting family filter and socket-find-admission design in the active change.
Repeat the same 48-window alternating main/replacement comparison, five native
floor batches per build and four separate cold sorted diagnostic windows, using
clean installed wheels and the same collector. Native floors now report owner
fallback rather than compatible native selection. Retain mutation, exact-hit,
resource and existing-test requirements. Add a fixed-capacity filter saturation
correctness diagnostic; collisions must never hide a resident result. Repeat
three alternating existing-test pairs separately. The earlier registered
identity-tail control was not started for the rejected build; reserve the same
finite twelve-window allowance for one specific uncertainty in the replacement,
declaring its question and schedule before running it. No campaign runs alongside
builds or tests.

### Final counter-write refinement

The preliminary replacement at `4d6aa936` completed its 48 workload windows.
Inspection found that filter increments/decrements still used locked atomic
read-modify-write operations despite exclusive ownership of all filter writes.
Replace them with atomic load/release-store updates under the same writer
exclusion, verify the ordering models, and freeze a new clean release build.
Repeat the same bounded 48-window comparison, five alternating native-floor
batches and three existing-test pairs for that final build; keep the preliminary
results as evidence rather than substituting them for the final comparison.
Add one identical generic identity lookup batch to each native-floor invocation
to investigate the preliminary identity-tail finding without MongoDB or timing
instrumentation. The same twelve-window uncertainty allowance remains available
for one explicitly declared finding after this final comparison. The final owner path also restricts queued admission to identity messages and
reuses existing namespace membership sets. Native floors use identical native
code and the same collector across the owner-only Python cleanup. No further
counter or family-filter variants are planned.
