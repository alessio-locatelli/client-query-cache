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

Build each revision in its own checkout and installed environment:

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

The registered memory benefit metric is incremental single-process PSS at `large-keys`
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
| Material gain and regressions                              | Per-block registered gain metric and all runtime/resource/existing-test controls    |
| Reproducibility and disposition                            | Immutable measured source URLs, build commands and independent fetch before removal |

## Decision and bounded follow-up

Report each paired block change, median and full range. Qualification requires
either the registered PSS reduction to reach 20% in every valid block, or
synchronous generic `find_one` hot-read CPU/completed read (including read
supervision) to fall at least 10% in every valid block. No other memory
checkpoint, runtime cell or isolated helper can substitute. Investigate every repeatable regression in
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

A clean repeat from the same installed M wheel, started at 08:49:43 UTC on
2026-10-27, completed all 124 checkpoints without a concurrent build or test
campaign. Both APIs and both small-result shapes again reached 64,001 entries,
3,776,008 charged bytes, 64,000 warm hits, 64,001 accumulated misses and zero
bypasses. Incremental warm PSS was 282,005,504 bytes (sync) and 281,927,680 bytes
(async) for long keys, and 47,042,560 and 46,997,504 bytes for short filters.
Raw output: `M-reference-memory-clean.json` in the disposable acquisition
directory. This repeat supplies the uncontended reference checkpoint; it is
still one baseline run, not a paired native acceptance block.

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

The spike supplies no complete-operation performance qualification. The
integrated owner below adds the namespace/availability/capture fences and LRU.

Before any candidate timing, add the synchronous generic hot-read CPU target
above to the initial memory-only registration. The preferred compact tuple
representation failed the semantic spike; the selected alternative retains the
Python key graph that dominates reference allocation attribution. The delta
spec already permits a complete-operation CPU gain, and this target uses an
existing registered cell with unchanged counts and controls. This amendment
preserves the memory target and does not waive any regression or conformance
gate. No native candidate has yet been timed, and no favorable native timing
diagnostic motivated the amendment.

## Integrated owner conformance before timing

`local_cache` is compiled only by `local-cache-prototype`. The lazy binding
getter initializes its Python class when explicitly selected; the reference
construction and shared-owner constructor stay available in the same wheel.
`research.native_process_local_cache.selection.select_native` replaces only the
two local manager constructors, before constructing managers in that process.
There is no public backend setting or fallback. An ordinary M wheel raises
`ImportError` when its absent native getter is requested; the expected failure
is retained in `M-no-native-feature.log`.

The backend-neutral call surface lives in the typing-only
`_core/contracts.pyi`; it creates no runtime protocol objects or storage graph.
The adapter inventory covers:

- Read and encoded-read methods for identity, namespace and find, deferred
  namespace misses, compatible sources, and alias resolution.
- Identity/namespace captures, encoded/value admission, unique matches and
  conditional alias/namespace cleanup.
- Namespace registration/inspection, generations, write/index events,
  clear/drop/recreation and conditional namespace release.
- Database availability, cumulative outcome snapshots, capacity properties,
  stream-cost forwarding, and close. The two metadata-probe invalidation hooks
  are no-ops locally: probe ownership remains exclusive to the shared owner.

Native storage uses indexed immutable records, chunked slots and linked LRU,
namespace and alias ownership. It retains original canonical Python keys and
immutable BSON bytes, with no Python `NamespaceState` or `CacheEntry` index.
Callbacks compare pinned records outside the mutex; membership changes advance
a non-reused revision. Capture handles combine namespace identity, stable slot
tokens, generations and availability observations. A stale compare cannot
delete a replacement. Close releases arena/table capacity even when captures
keep the empty authority alive. The feature-only `_ownership` diagnostic
reports namespace, identity, alias, capture and source counts outside timed work.

Installed-wheel conformance has passed 43 owner cases, including 100 generated
collision/eviction schedules against the reference. Cases cover abandoned
captures, original-key reclamation, Python/native cycles, reentrant finalizers,
negative comparisons followed by insertion, reentrant stale admissions and
parallel mutation during blocked equality. A spawned worker constructs real
sync/async managers, checks that their coordinators hold the same native core,
and verifies that the shared constructor remains the reference.

The explicit native pytest plugin additionally ran
15 availability/state-machine cases, 19 find outcome/covering/collision cases,
16 unique-admission/cleanup cases and five lifecycle cases. The four excluded
unique-admission instances pause Python LRU methods; native stale-publication
and replacement cases instead exercise its outside-lock comparison boundary.
Other tests of Python storage internals remain reference tests. Native ownership
counts, original-key weak references and pressure tests cover reclamation on
its actual representation.
The 32 identity-normalization helper cases also passed, but do not execute a
core and are not counted as native storage conformance. Owner cases separately
exercise numeric identity equality and invalidation through real native storage.

The native-selected public run passed 665 sync/async collection, bound-session
and cursor cases, including codecs, isolated prefixes, native errors, stream
transitions, batch failures and cancellation. Public cursor tests inspect
resident entries rather than Python family dictionaries; owner-level cases
check native family reclamation. The plugin asserts the actual native type for
core/manager fixtures and shared core identity for manager/coordinator pairs.
Review exposed a capture-only key cycle rooted by the native identity index;
adding a capture clear hook alone would not make that reachable cycle collectible.
The corrected candidate uses a GC-tracked native identity handle, with weak
index ownership until a value is resident. Its alias references are traced by
the same handle, and comparison snapshots pin it. Live-core cycle cases cover
pending captures, post-eviction identities, alias keys and alias values. The
additional handle/weak-reference allocations remain in the measured build.
The concurrent raising-comparison case checks preserved insertion, unchanged
outcomes and unchanged LRU order. The cursor cancellation barrier now has a
bounded wait and fixture-owned task cleanup. The corrected native public run
again passed all 665 cases.
These are correctness runs; their elapsed times do not qualify performance.

Reproduce the owner and public runs after installing the feature wheel:

```bash
.venv/bin/python -m pytest research/native_process_local_cache/test_owner.py -n 0 -q
source scripts/testcontainers-bridge.sh
.venv/bin/python -m pytest -p research.native_process_local_cache.pytest_plugin tests/synchronous/test_collection.py tests/asynchronous/test_collection.py tests/test_bound_sessions.py tests/test_cached_cursors.py -n 0 -q
```

Candidate timing, the full existing-test timing comparison, the remaining
stream/concurrency conformance and final ordinary-wheel controls are pending.

## Collector validation before the candidate freeze

The public collector now verifies returned values after each latency interval,
records origin command deltas and worker implementation/import paths, and
requires one complete catalogue traversal consisting entirely of cache hits.
Large-occupancy setup has a finite 300-second readiness/warmup deadline. The
measured CPU/throughput scope includes value checks and checkpoint bookkeeping;
individual read latencies exclude those checks. Only the small-result controls
take intermediate residency snapshots, every 256 reads, in addition to their
start/end checkpoints. Every revision uses the same acquisition harness source.

A reference smoke run used 16 keys and 64 samples/worker across eight
model/path/state windows. Each completed 256 reads; independent hot windows
recorded 256 hits, cold windows 256 misses, and bypass counts were zero. This
reduced smoke is collector validation, not a registered performance cell.

The full-occupancy long-key cold control then passed both APIs and both paths.
Each of eight independent workers began with 64,001 entries and 3,776,008 charged
bytes. After 8,192 disjoint reads, each held 71,089 entries and 4,194,251 bytes,
with exactly 1,104 evictions (including the eight-byte probe). All 32,768
independent reads per window missed, with zero bypasses. The worker type was the
installed reference core throughout. Raw outputs are
`R-collector-validation.json` and `R-occupancy-collector-validation.json` in the
disposable acquisition directory. Neither run supplies a native gain claim.

### Extended acquisition entry points

Use the committed C checkout as the working directory for every revision, with
its harness and each revision's absolute installed interpreter. This supersedes
the earlier per-checkout harness invocation: starting in M shadows the extended
harness even when `PYTHONPATH` names C. No `src` directory belongs on that path.
Build explicit release wheel artifacts in separate output directories, using
the repository's `maturin build --release --zig --compatibility manylinux_2_28
--locked` settings and `CARGO_ZIGBUILD_PYTHON_PATH` pointing to that checkout's
`scripts/zig-linker.sh`. Add `--features local-cache-prototype` for C only.
Install those exact artifacts with `uv pip install --python <interpreter>
--no-deps --reinstall <wheel>`, retaining the frozen environment dependencies.

Run one revision/block with:

```bash
/path/to/installed/python -m research.native_process_local_cache.acquire --label M --block 0 --wheel /path/to/M.whl --existing-nodes /tmp/agents/native-local-20261027/existing-nodes.txt --output /tmp/agents/native-local-20261027/cohort-1/b0-M
```

Repeat with R/N and the same C wheel (N selects native), following the registered
block orders. `--components public memory contention tests` is the default;
component subsets allow recording a failed/repeated component separately without
silently replacing completed observations. The controller retains wheel and
extension hashes, installed paths, harness revision, clock resolution, limits,
values/outcomes/residency and rejected-cell reasons. Memory uses the existing
child/phase collector. Public workers report RSS/USS/PSS and lifetime peak RSS,
plus a separate untimed 50 ms admission-stability observation; its CPU is
excluded from read CPU and reported separately. The measured CPU total includes
read supervision. Value guards run outside individual read latency but inside
process CPU and throughput intervals. Peak RSS includes setup and warmup; it is
not an allocation attribution.

The contention entry point is `python -m
research.native_process_local_cache.contention --output <raw.json>`; add
`--native-local` only for N. It reuses the public dataset/provenance and command
collectors. Its absolute, finite writer schedule needs separate acknowledgement
and offered/completed records rather than the public CLI's duration-dependent
writer. The uninstrumented R validation completed both 1/4-thread cells with
80,000 completed reads, 1,000 writes and exactly 1,000 applied invalidations,
all inside the active read interval. Both cells had 79,001 hits, 999 misses and
zero bypasses. This is collector validation, not candidate performance evidence.

Existing-case N timing selects native manager construction while direct tests
of the retained reference core continue to exercise that core. The acquisition
plugin explicitly keeps Python-storage inspection, reference-class fault
injection and cursor allocation implementation probes on reference construction;
its finite selection is recorded in `pytest_plugin.py`, and JUnit properties
record the selected manager constructor per case. It asserts the actual backend
and coordinator identity for manager-valued fixtures. These representation-specific
cases do not establish native conformance; the actual native owner ordering and
reclamation suite plus public behavioral cases provide that evidence. The same
frozen node IDs and test bodies run for M/R/N; new tests remain separate.

The prototype controller accepts M/R/N only. F is deliberately rejected until
ordinary-build integration supplies default-native assertions without private
selection in public, memory and contention collectors. Contention throughput
uses the scheduled origin through final completion; actual first/last call
endpoints remain the overlap interval, and initial/individual-call lateness is
retained rather than disappearing from the denominator.

The broad N construction conformance run passed 4,363 cases and exposed four
editable-path assertions, one reference-class fault-injection selector mismatch,
and two fixture cleanup ordering errors caused by borrowing the tests' own
`monkeypatch` fixture. The source assertion now follows the actual imported
package; the selector has an independent patch context and an explicit reference
case for that injected fault. The seven affected cases and all 43 owner cases
then passed together (52 cases, because the fault check has three parameters and
the source assertion four). These runs predate frozen C and are correctness
checks only; their duration is not existing-test performance evidence.

Native public-contract coverage includes both API directories' collection/read
methods, metadata and codec/document-class cases; `tests/test_cached_cursors.py`
covers complete lists, compatible sources, partial/cancelled/faulted cursors and
caller-owned results, and `tests/test_bound_sessions.py` covers session bypass.
The real-manager stream integration cases exercise native availability and
recovery. Direct reference-coordinator fakes and the explicit representation
probes remain reference cases. `test_owner.py` adds actual native collision,
reentrant/concurrent comparison, stale-admission, ABA, GC, alias and compatible
source cases; its randomized histories compare against a distinct reference
instance. The selector's module patch is restricted to `tests.*` and does not
replace that differential reference instance.

C uses a separate installed environment at `/tmp/agents/native-local-20261027/candidate-env`; the working checkout remains the clean, committed C branch. This separates acquisition imports from the editable environment used for the source coverage gate. The matched explicit M/C wheel builds completed in release mode with the registered Zig/glibc settings. The reference collector recheck verified all eight sorted-read model/path/state cells, complete values, charged bytes, admission stability and CPU resolution.

The acquisition host is an Intel Core i3-13100. Toolbx does not expose `cpu.max`, `memory.max` or `pids.max` at the cgroup mount root; record that absence rather than inferring cgroup limits. Process limits/affinity and RSS/USS/PSS remain available, and each server has its explicit container limits. Retain the full host and wheel hashes in the untracked `host-and-artifacts.json`; the results report will identify the reproducible source and build settings.
