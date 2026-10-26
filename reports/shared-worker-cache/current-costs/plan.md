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

### Final sync identity control

The final three pairs show higher sync identity cold reader CPU in every pair
(5.3–5.9%) with disjoint CPU ranges, higher P95/P99 and lower throughput. Use the
remaining twelve-window allowance only for this finding: six additional
main/candidate pairs of the unchanged sync identity cold workload, 1,024 calls
per worker and 1,024 warm keys, shared only. Odd pairs run main then candidate;
even pairs reverse order. Keep all results and stop at twelve windows. The
native generic lookup diagnostic is separate and cannot dismiss an end-to-end
regression. No build, test or other measurement campaign runs concurrently.

### Bounded attribution for the remaining identity-tail finding

The six final controls retain higher candidate sync identity cold P99 in every
pair. CPU directions vary, and the dependency C extensions are byte-identical.
Do not accept the finding as harmless noise. Add exactly two transport-only
identity sync cold diagnostic windows (one per build, 1,024 calls per worker)
and two separate cProfile windows (one per build, 256 calls per worker). Inspect
all four worker profiles from each build, actual queue/socket counters and owner
admission outcomes. Exclude these instrumented durations from timing tables.
Stop attribution after these four windows and use the evidence to fix a concrete
regression or report a blocked design choice; do not start more speculative
architecture or timing variants.

### Owner-admission attribution extension

The four attribution windows found identical worker admission bytes/counts and
no queue drops, matching worker key/lookup/capture call counts and near-equal
native worker times. Owner busy time increased from 0.165 to 0.183 seconds for
4,096 identity admissions. This specific owner-side finding warrants one
extension of the preceding stop: exactly two owner-only cProfile windows, main
and candidate, with the existing sync identity cold collector at 256 calls per
worker. A temporary launcher wraps the spawned owner entry point; it changes no
repository runtime code. Inspect normalized admission/native-publication costs,
exclude profiled durations from timing evidence, and stop after this pair. No
additional uninstrumented timing or architecture variants are authorized by
this extension.

### Rust key-preparation correction

The user directs rewriting measured slow work into Rust. Replace the rejected
native membership/admission designs with the paired-key encoder in the current
OpenSpec design. Keep the original native index, generic identity lookup and
owner request representation. No prior native candidate qualifies this build.

Before timing, freeze the implementation, build clean installed release wheels,
and verify dependency versions and import origins. Acquire exactly 48 matched
shared-only windows: three revision pairs, sync/async, identity/sorted and
hot/cold, using the initial populations and call counts. Blocks one and three
run main then candidate and sync then async; block two reverses both orders.
Retain every result and all expected hit/miss, stream and bypass counters. No
other builds, tests or acquisition campaigns may run during workload timing.
Compare latency, throughput, worker/owner CPU and group PSS under the baseline
measurement limits. An unexplained reproducible regression blocks promotion.

Separately acquire four sorted cold transport diagnostic windows (both builds
and models), and four worker-profile windows (the same, 256 calls per worker).
Inspect all four worker profiles in each window. These instrumented durations
are not timing evidence. Compare paired-key preparation CPU against the two
baseline encodings in five alternating isolated batches of 10,000 distinct
canonical families, with no retained cache hits; preserve specialized scalar
callback counts and exact byte checks. These are binding/encoding floors, not
MongoDB latency claims.

Compare the same existing test selection as the native trials in three
alternating main/candidate pairs. Add `and not native-key` to exclude the new
fixture and limit cases, retaining the original 279 cases in both builds. New
wire/integration cases belong to the separate complete coverage gate.

If the 48 windows expose one repeatable regression, use at most twelve more
unprofiled windows (six alternating pairs) solely for that finding. Retain all
controls and stop at that cap. Further instrumentation must answer a specific
remaining attribution question; it does not authorize speculative variants or
acceptance of a regression.
