# Native process-local cache acquisition

Registered on 2026-10-27 before baseline timing or candidate construction.
The [design](../../openspec/changes/prototype-native-process-local-cache/design.md)
defines the implementation boundary; the
[evaluation contract](../../openspec/changes/prototype-native-process-local-cache/specs/process-local-cache-evaluation/spec.md)
defines acceptance. This file owns the acquisition choices and observations.
No historical measurement is a newly acquired baseline.

## Source, builds, and isolation

Freeze main as `1f70de76b6bc9fdcc4ab7cf0d4a8a4d784d9588e` (M).
Record the immutable candidate commit (C) before candidate timing. Compare M,
the reference selected from C's wheel (R), and native selected from that same
wheel (N). Repeat final ordinary-wheel acquisition (F) against M after removing
temporary selection. Record wheel and extension SHA-256, imported paths, Python,
dependency versions, kernel, CPU, libc, MongoDB image digest, and resource limits.

Build each revision in its own detached checkout and installed environment:

```bash
git worktree add --detach /tmp/agents/native-local-20261027/main 1f70de76b6bc9fdcc4ab7cf0d4a8a4d784d9588e
cd /tmp/agents/native-local-20261027/main
uv sync --locked --no-editable --group docs --quiet
source scripts/testcontainers-bridge.sh
.venv/bin/python -c 'import client_query_cache; import client_query_cache._shared_index as native; print(client_query_cache.__file__); print(native.__file__)'
```

`uv sync --no-editable` installs Maturin's release wheel using the committed
build settings. For C, add `--config-setting build-args=--features=local-cache-prototype`
to that sync command. F uses the M command without that argument. Confirm the
native build profile before acquisition; never substitute a debug build.
Use the frozen lock for all environments. Run harness modules from each source
checkout, with no `src` entry in `PYTHONPATH`; children must report their installed
implementation. Native selection happens before manager construction and must
fail visibly if unavailable. Keep MongoDB in a disposable container and stop
other test/build/benchmark campaigns during acquisition.

Initial environment preparation verified CPython 3.14.7, PyMongo 4.18.2, and
imports under the detached checkout's `.venv/lib/python3.14/site-packages`.
The frozen Compose image is
`mongo:9.0.4@sha256:dc28ed5a9d0fc616903c3f463bb1e53b92b49f441721b91926e87d90bf957ce8`.
The public harness limits MongoDB to two CPUs and 1 GiB. The memory harness
uses its existing container fixture; record its different server scope rather
than presenting its memory figures as four-worker figures.

## Registered cells and ordering

The primary benefit metric is incremental single-process PSS at `large-keys`
`warm`: subtract each process's baseline, then subtract the matched direct
growth. Only this checkpoint may qualify memory retention. Record RSS and USS
alongside PSS. Small-entry, post-eviction, document, and lifecycle checkpoints
are descriptive memory controls, not alternative benefit targets.

Each block uses both execution models. Public cells use four worker processes,
one serial caller per worker, majority reads, no writer, and complete results:

| Shape                                  |             Catalogue per core |                     Payload | Hot samples/worker | Cold samples/worker |
| -------------------------------------- | -----------------------------: | --------------------------: | -----------------: | ------------------: |
| `identity`                             |                          1,024 |          4,096-byte payload |             16,384 |               1,024 |
| Generic `find_one`, descending ordinal |                          1,024 |          4,096-byte payload |             16,384 |               1,024 |
| Sorted `find`, 16 documents            |                     128 groups | 4,096-byte payload/document |              2,048 |                 256 |
| Short-filter small result              | observed memory warm occupancy |        exactly 59-byte BSON |             16,384 |               8,192 |
| Per-request 48-value `$in` filter      | observed memory warm occupancy |        exactly 59-byte BSON |             16,384 |               8,192 |

Run each shape hot/cold and direct/independent for M/R/N: 120 windows/block,
600 windows across five blocks. The two small-result shapes use a 4 MiB budget,
64,000 distinct setup requests and the memory harness's initial catalogue probe.
Use the actual observed count (historically 64,001, not assumed) including that
probe. The hot traversal must cover the entire resident catalogue before timing;
timed offsets rotate by block. Preserve equal entry count, used BSON, occupancy
ratio, and catalogue coverage before/after timing. Cold reads begin from that
same checkpoint and use disjoint keys in the same order; compare admitted bytes,
entry counts, and evictions, including the transition to eviction. Never replace
these controls with a 4,096-key working set. Reject unmatched checkpoints.

Before candidate timing, increase the two small-result cold cells from 4,096
to 8,192 calls/worker: the observed checkpoint has room for 7,089 more 59-byte
entries, so 4,096 calls would not exercise the registered eviction transition.
No candidate results were collected before this correction.

Use five revision orders: M/R/N, N/R/M, R/M/N, N/M/R, M/N/R.
Within a revision rotate the first shape by block, alternate model order, and
reverse hot/cold and path order on odd blocks. One window per cell per block
is one replication; individual requests are not replications. Final M/F orders
are M/F, F/M, M/F, F/M, M/F, using the same cells and schedules.

Run fresh-process memory cells `documents`, `small-entries`, `large-keys`, and
`cycles`, both APIs, direct/cached, once per revision per block (48 processes
per M/R/N block). Preserve existing scenario counts, budgets, and phase order
from `research.process_memory.measure`; direct R/N controls remain separately
labelled to expose wheel overhead. Checkpoints include imported/manager baseline,
cold, warm, eviction, close, trimmed, and all five cycle fill/close pairs where
the scenario supplies them. Keep per-phase peak RSS and cgroup observations.

## Contention and final shared controls

Contention cells use one spawned process, one synchronous manager and one
caller-owned MongoClient created before 1 or 4 reader threads. Prewarm 1,024
identity documents with 4,096-byte payloads. Run 20 seconds at offered aggregate
4,000 reads/s (round-robin identities, equal thread shares); the outside writer
updates successive catalogue identities every 20 ms with majority acknowledgement.
Use monotonic absolute schedules and record offered/completed work and lateness;
never compensate for lag by silently dropping calls. Synchronize readers/writer
start. One cell per thread count and revision per block; repeat for F/M.

Record stream invalidations and their monotonic application timestamps from the
same manager, plus completed-write timestamps and read-interval endpoints.
Require at least one processed invalidation strictly within the active read
interval, continued reader progress, identical manager identity across threads,
and outcome totals equal to completed reads. Drain writes/invalidations after
the timed interval with a 30-second deadline; report tail lag and drain CPU
separately. Compare actual writes, invalidations, and lag before interpreting
speed; unmatched effective pressure is inconclusive. Record P50/P95/P99,
throughput and process CPU/read, excluding writer and MongoDB CPU.

F/M shared controls use the public harness's unchanged 32 MiB budget, 40 MiB
arena and 16,384 slots: identity over 1,024 keys and sorted find over 128 groups
of 16, both APIs, four workers, 4,096-byte payloads, hot only, no writer.
Use 65,536 identity or 8,192 sorted samples/worker, one cell/block. Require equal
complete residency and no measured misses, bypasses, origin reads or owner
selections. Record worker-plus-owner CPU/read and latency/throughput.

Separately run one fresh import probe and one fresh shared startup/resource
probe per shape/API/revision/block. Import intervals enclose public-library
import only. Shared startup begins at owner creation and ends when owner and
all workers report attachment/metadata readiness, before result warmup. Record
wall and all participating process CPU. Capture each process's RSS and summed
worker-plus-owner PSS at readiness and after the matched catalogue is resident.
Exclude collector, seeding, MongoDB, build, and test processes. Extend the existing
collectors for these phase observations; do not infer them from post-read PSS.

## Commands and observations

For the existing public shapes, invoke each table cell with its registered
sample count, model, path and workload, for example:

```bash
.venv/bin/python -m benchmarks.public_shared_cache --method find_one --hot-keys 1024 --document-bytes 4096 --samples 16384 --repetitions 1 --models sync --paths independent --workloads hot --output /tmp/agents/native-local-20261027/M-b0-find_one-sync-hot.json
.venv/bin/python -m research.process_memory.measure run --runs 1 --seed 197 --scenarios documents small-entries large-keys cycles --output /tmp/agents/native-local-20261027/M-b0-memory.json
```

Increment memory seed by block. The initial baseline uses existing entry points;
repeat matched reference cells with the extended harness before comparing C.
Task 3.1 adds the small-result/topology/selection observations above; register
its exact CLI invocations here before candidate timing. No missing harness
observation may be inferred from a different topology or a historical result.

Profiles are separate from timing: generic `find_one`, both APIs, hot/cold,
independent, 256 calls/worker, one repetition and `--profile-dir` under the raw
directory. Attribute exclusive/cumulative profile time to lookup, canonical/key preparation,
generation checks, LRU, BSON encoding/decoding, and remaining calls. Run separate
`tracemalloc` snapshots around baseline/population/close for Python retained
allocations; reconcile with process PSS/RSS, never call traced bytes total memory.
Collect native allocation attribution after C exists and only profile the target
or regressed controls. Profiles cannot establish a runtime gain.

For every window retain expected-value checks, hits/misses/bypasses, actual
residency, origin-command counts, elapsed time and raw CPU deltas. Include reader
supervision CPU in completed-work runtime totals. Measure residual admission
work/peaks in an additional untimed window through stable admission completion.
Workers use `time.process_time`; record `time.get_clock_info("process_time")`.
The shared owner uses its POSIX process CPU clock, obtained once with
`clock_getcpuclockid` and sampled with `time.clock_gettime`; record
`time.clock_getres` for that clock. Read-supervisor and startup CPU observations
must record their clock as well. Ensure each nonzero CPU component exceeds
100 quanta of its own counter; classify a component below resolution as
unresolved rather than treating zero as free work. Lengthen matched windows or
resolve the collector's precision before C timing. On this host both clocks
report 1 ns resolution. The original collector's 10 ms ticks are insufficient
for short owner intervals and are not used in matched candidate controls.
Reject wrong results, incomplete catalogues, unexpected hot misses/bypasses/origin
reads, unmatched cold trajectories, coarse counters, setup errors, deadline
failures or host interference. Retain every rejected window and its reason.

## Existing tests and conformance

Freeze selected node IDs by collecting M with its installed environment:

```bash
.venv/bin/python -m pytest --collect-only -q -n 0 --log-file=/tmp/agents/native-local-20261027/collection.log
```

Sort only `tests/...::...` lines, join with LF including a final LF: 4,367 IDs,
SHA-256 `595525f35b718ea67cd368334e97298943b07d1f36cdb91281833ebbed7e5bc8`.
This is the exact default non-memory set at M, not a selection of favorable cases.
Retain that list untracked and regenerate from M to reproduce. Run those IDs
against each installed environment once/block, sequentially with `-n 0`, the
same pytest settings and isolated fixture startup state. Record total duration
and fixture/collection scope. Run added conformance cases separately, never mix
their cost into the existing-case comparison.

| Acceptance obligation                                      | Named check                                                                         |
| ---------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| Explicit private selection and final ordinary construction | Installed-wheel child/core identity and setup-error cases                           |
| Existing read semantics                                    | Real-core sync/async, cursor, session and codec conformance                         |
| Key equality and callback versioning                       | D3 differential suite and deterministic mutation/equality barriers                  |
| Generations, aliases, compatible sources and reclamation   | Real-core admission, availability, LRU, namespace, lifecycle and concurrent cases   |
| Equivalent complete work and outcomes                      | Per-window values, origin counters, residency and trajectory checks                 |
| Full process memory and resource lifetime                  | Fresh-process checkpoints, phase peaks, close/trim and repeated cycles              |
| Qualifying memory occupancy and small-read runtime         | Both small-result public cells above                                                |
| Same-core contention                                       | Thread identity, processed-invalidation overlap and pressure records                |
| Final shared/import/startup effects                        | F/M warm, import, readiness and resident resource probes                            |
| Material gain and regressions                              | Per-block primary PSS reduction and all runtime/resource/existing-test controls     |
| Reproducibility and disposition                            | Immutable measured source URLs, build commands and independent fetch before removal |

## Decision and bounded follow-up

Report each paired block change, median and full range. The registered primary
PSS reduction must reach 20% in every valid block. No other memory checkpoint
or isolated helper can substitute. Investigate every repeatable regression in
latency, throughput, CPU, resources or existing tests; correct it or obtain
explicit approval before retention. Mixed directions and unresolved controls
remain inconclusive. Allow one additional five-block cohort for one named
uncertainty and one attributed candidate correction with its remeasurement;
retain cohorts separately. A semantic blocker stops construction. Record D3
layout and synchronization evidence here before completing the native adapter.

Raw outputs stay under `/tmp/agents/native-local-20261027/`. The results report
will retain source identities, attribution, invalid reasons and the decision;
this registration does not assert that acquisition or conformance has passed.

## Reference acquisition and attribution

The first reference acquisition used M's installed wheel and original harnesses:
24 public windows (the three original shapes, both models, direct/independent,
hot/cold), 124 fresh-process memory checkpoints across the registered scenarios,
and four separately profiled generic-read windows. All observed independent hot
reads hit, cold reads missed, and bypass counts were zero. These are preliminary
reference observations, not candidate comparisons or five-block gain evidence.
The original public harness checks nonempty results and aggregate outcomes but
does not supply the full value/origin/residency observations required of the
extended comparison. Retain those missing-observation reasons and repeat its
reference cells with the extended harness. Environment/commit preparation also
overlapped the initial memory campaign; that campaign is diagnostic only and
cannot serve as an acceptance block.

Both small-result shapes reached exactly 64,001 entries and 3,776,008 charged
BSON bytes at `warm` in both APIs: 64,000 code results of 59 bytes and the setup
probe's 8-byte result. Every warm code read hit, with zero bypasses. The observed
budget occupancy is 90.03%. Baseline-adjusted cached-minus-direct warm PSS growth
was 280,252,416 bytes (sync) and 280,313,856 bytes (async) for long keys; short
filters used 45,297,664 and 46,981,120 bytes respectively. These single-run values
describe the reference's scale; they establish neither a native saving nor an
RSS bound.

The default cProfile timer measures elapsed time, including waits; its tables
must not be called CPU attribution. Summing exclusive profile time across four
256-read workers gives the following microseconds/read:

| Model/state | Canonical/ordered key preparation | Lookup | Namespace/generation/availability helpers |   LRU | BSON/codec helpers |
| ----------- | --------------------------------: | -----: | ----------------------------------------: | ----: | -----------------: |
| Sync hot    |                             89.13 |  11.60 |                                     14.75 |  9.67 |               6.99 |
| Async hot   |                             62.24 |   8.48 |                                      8.92 |  7.05 |               4.93 |
| Sync cold   |                             62.06 |   4.57 |                                     14.77 | 13.75 |              22.50 |
| Async cold  |                             49.29 |   5.30 |                                     11.90 | 13.05 |              17.72 |

The categories are disjoint: canonical/order-sensitive modules, lookup-named
methods, generation-named methods plus `_namespace`, `_is_database_available`,
`_capture_database_availability`, `_is_registered_state`, LRU module, and codec
module/native BSON functions. Remaining time includes facade work, locks,
classification, driver calls and waits. Generation work within larger methods
is not separately resolved. Profiler overhead is substantial; only the separate
uninstrumented windows supply operation latency and process CPU.

The separate allocation acquisition reuses the memory harness's builders and
phases with 5,000 code reads per shape/API and no eviction tail:

```bash
PYTHONPATH=/path/to/acquisition-checkout .venv/bin/python -m research.native_process_local_cache.profile_allocations --api sync --scenario large-keys --output /tmp/agents/native-local-20261027/M-allocation-sync-large-keys
```

Repeat for async and `small-entries`, using M's installed interpreter/environment.
Snapshots compare `cold` with `baseline`; `evict` is an explicitly empty phase,
not eviction attribution. Dumping snapshots adds traced transient allocations,
so traced peaks and process memory from this instrumented run are not acceptance
metrics. Cold retained traced bytes were 3,246,099/3,281,302 (short sync/async)
and 19,846,660/19,870,685 (long sync/async). Long-key filter leaves retained
13,641,632 bytes and canonical tuples about 4,559,000 bytes, while manager and
LRU source locations retained 787,856 and 373,044 bytes in each run. Native
metadata alone cannot eliminate the retained Python key graph; its total-process
benefit remains a measurement question.

Worker CPU windows use the verified 1 ns process clock. The shared collector now
resolves the owner's POSIX process CPU clock once while the owner is alive and
samples that same clock at both boundaries; it records the clock resolution.
Real spawned-process checks compare that counter to the child's own CPU reading
and verify that a stopped owner produces a visible error. This replaces the
10 ms owner ticks without claiming that a rounded zero represents no work.
The final matched acquisition must use this same collector on M and F.
The first shared clock-validation command ran from M's source directory, whose
harness shadowed `PYTHONPATH`; it lacks the new resolution field and is excluded
from collector validation. The corrected run used the acquisition checkout with
the absolute M interpreter path, verifying both import paths first. Both APIs
recorded 262,144 hits, zero misses/bypasses and zero owner requests; measured
owner CPU was 0.120590 seconds (sync) and 0.129671 seconds (async), at 1 ns
reported resolution.
For every cross-revision run, use the same acquisition checkout as working
directory and each revision's absolute installed interpreter; changing only
`PYTHONPATH` while staying in another source checkout is insufficient.

## D3 key and synchronization spike

The feature-only `local_spike` module tests two representations before adapter
construction. Reconstructing compact tuple nodes changes supported mixed
equality: an opaque hashable value can recognize the original canonical tuple
by identity. The deterministic differential case retains both lookup orders;
one order incorrectly misses after reconstruction. This rules out that compact
representation, not all possible future key representations.

Select D3's reference-preserving alternative: Python key references with native
entry metadata. The spike pins keys/values through owned references, compares
outside its mutex, and commits only after revalidating a non-reused revision.
Every insertion, replacement or clear changes that revision; misses create no
historical bucket metadata. The global revision is a conservative feasibility
mechanism, and its vector LRU is not the production performance candidate.

Owner-level cases cover canonical generated values, deliberate collisions and
generated operation order, mixed opaque/scalar equality in both orders, identity
numeric equivalence versus discriminator subtype distinctions, embedded order,
codec-registry identity, reentrant replacement, and deterministic concurrent
clear/replacement/negative-comparison insertion for lookup and admission.
Interrupted lookup/admission commits no pending outcome or LRU mutation; callback
mutations remain effective. A weak-reference finalizer reenters the owner during
reclamation, verifying that Python reference destruction runs outside the lock.
Finite callback mutations terminate and return the replacement token/value,
with exactly one committed lookup outcome.

Reproduce with a feature wheel installed from the acquisition source:

```bash
uv sync --locked --no-editable --group docs --quiet --config-setting build-args=--features=local-cache-prototype
.venv/bin/python -m pytest research/native_process_local_cache/test_key_spike.py tests/core/test_canonical.py tests/benchmark/stream_cost/test_process_cpu_clock.py -n 0 -q
```

The full adapter must preserve these callback and ownership properties while
adding the namespace/availability/capture fences and scalable LRU specified in
D2. The spike supplies no complete-operation performance qualification.
