# Design

## Context

See [proposal.md](proposal.md#why) for motivation. The [version 4 study](../../../docs/development/research/shared-worker-cache-feasibility.md) and its [registration](../../../reports/shared-worker-cache/v4/registration.md) are the baseline protocol. The facts below shape this design:

| Observation                                                                                                                                                                                                                                                       | Consequence                                                                                                                                                                                                          |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Independent managers used 257–350 µs of total CPU per request in v4 screening. At ×1.10, that leaves 25.7–35 µs of extra CPU per request.                                                                                                                         | Any design whose per-hit mechanism alone costs about that much cannot pass, however well its adapters are written.                                                                                                   |
| v4's sequential diagnostic measured 12 µs of caller CPU per 4 KiB hit through the blocking socket owner, before any owner work.                                                                                                                                   | A design that keeps the round trip starts close to the allowance even with a native owner.                                                                                                                           |
| A prototype hit runs, inside the owner, the authorization, stream activation, availability, progress-lease and epoch checks (`SharedCacheOwner._gate`, `_epoch_reply`), then `CacheCore.lookup_identity_encoded`.                                                 | A local hit must reproduce exactly these checks from published state.                                                                                                                                                |
| `CacheCore` invalidates lazily. `record_write` advances the namespace and identity generations and drops aliases, but leaves the entry resident until the lookup's generation comparison rejects it. Namespace resets (`_bump_epoch_and_reclaim`) remove entries. | A published index must mirror invalidation eagerly. Watching residency changes alone would keep serving entries that have been written.                                                                              |
| `WeightedLru` is the only residency structure. Every admission, displacement, eviction and removal goes through `conditional_put`, `remove_exact` or `clear_all`, and hits call `touch`.                                                                          | One residency listener at this level sees every entry that leaves the cache. Entering the LRU is not admission: `_finalize_put` re-checks validity under the namespace lock afterwards and rolls stale entries back. |
| `CacheEntry.value` holds the encoded BSON as `bytes`.                                                                                                                                                                                                             | Publishing into shared memory would duplicate every payload, unless the owner's core can keep the payload in the shared arena instead.                                                                               |
| v4 group PSS ratios were 0.60–0.61 at four workers and 0.48 at eight.                                                                                                                                                                                             | A second copy of the 68 MiB hot set would push the four-worker ratio toward the 0.75 limit.                                                                                                                          |
| The active change `benchmark-concurrent-worker-workload` makes the harness's paths, phases and cells registration-driven (its tasks 1.1–1.2).                                                                                                                     | New candidate paths should plug into that mechanism, not into a third hard-coded path list.                                                                                                                          |
| The test host is x86-64. The project has no native code; the published wheel is built with `uv_build` from `src/`. Coverage measures the `benchmarks/` package, but not `research/` (no packages there).                                                          | Native code needs a toolchain decision. Code that tests import must be built in contributor setup and CI, while exploratory programs can stay in `research/`.                                                        |

## Goals / Non-Goals

**Goals:**

- Decide, with registered evidence, whether a candidate meets every version 4 promotion criterion (including capacity) at four and eight workers.
- Keep `CacheCore` the single authority for admission, eviction and generations in every candidate.

**Non-Goals:**

- A supported shared-cache mode, public API, deployment guide or published native wheel. Those belong to a later integration change, opened only after a passing verdict.
- Serving finds, counts, aliases or non-`_id` reads locally. They keep the existing owner RPC, as in v4.
- Platforms other than Linux, free-threaded CPython, multiple hosts and sharded clusters.

## Decisions

### Candidate families

| Family                                                                                                                 | Advantages                                                                                                              | Costs and risks                                                                                                                                                                            | Unknowns                                                                                               | Disposition                                                                                                                                                   |
| ---------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **A. Shared index with local validation.** The owner publishes identity entries and validity words; workers read them. | No syscall, owner work or wakeup on a hit. Owner capacity stops limiting hit throughput. Asyncio hits need no awaiting. | Workers check validity outside `CacheCore`. That needs eager invalidation mirroring, fencing for torn reads and owner loss, a shared allocator, and native atomics on weakly ordered CPUs. | PyO3 call overhead per hit; the payload-store seam's cost to standalone hits; allocator fragmentation. | Leading candidate, subject to [floor selection](#floor-diagnostics-and-selection).                                                                            |
| **B. Native owner hot path.** A native owner thread answers identity selections from the same index without the GIL.   | Workers keep v4's simple fencing (an RPC deadline catches a paused owner within 100 ms). No worker mapping.             | Each hit still pays socket syscalls and a cross-process wakeup on both sides. B uses A's index plus a round trip, so it can never cost less CPU than A.                                    | Native round-trip CPU per hit on this host.                                                            | Built only under the [selection rule](#floor-diagnostics-and-selection).                                                                                      |
| **C. Amortized round trips.** Coalesce a worker's concurrent selections into one frame.                                | Divides per-message syscall cost by the batch size.                                                                     | Helps only with several requests in flight. Synchronous thread-per-request workers cannot batch without an extra dispatcher thread. Waiting to fill a batch adds latency.                  | Achieved batch size at four requests in flight.                                                        | Treated as a variant of B, with floor F3 below. Not a separate candidate.                                                                                     |
| **D. Several owners per host, sharded by namespace.**                                                                  | Raises owner capacity.                                                                                                  | Does not lower the CPU per hit. The registered workload has one namespace, so it would not shard.                                                                                          | None that this change needs.                                                                           | Not built. A removes owner work from hits. If B is the only survivor and fails only on capacity, the report opens a ticket rather than extending this change. |
| **E. Optimize the Python owner.**                                                                                      | No new toolchain.                                                                                                       | Even a fourfold cut in v4's 120–135 µs of owner work, added to 12 µs of caller CPU, exceeds the allowance.                                                                                 | None that changes the conclusion.                                                                      | Rejected. B's floor is its lower bound.                                                                                                                       |
| **F. LMDB or shared-memory payloads behind the round trip.**                                                           | Removes payload copies.                                                                                                 | v4 measured payload work below 3% of owner time, and the round trip remains.                                                                                                               | None.                                                                                                  | Already rejected by v4. No experiment.                                                                                                                        |

### Floor diagnostics and selection

The draft v5 registration records this rule before any floor is measured. Floors are exploratory, live in `research/shared_index_floors/` and time 4 KiB `primary` entries. They run against a floor prototype that contains only the per-hit machinery: a preallocated fixed-slot table with the version protocol, atomic copies, the read checks, a hit-ring append, and an echo-owner thread. Only F1 performs the ring append. B's owner sees every hit and can record recency itself, so F2 and F3 omit it. The allocator, descriptor sealing, publication from `CacheCore`, ring draining and model tests come only after a candidate is eligible, so an early stop wastes little work. Each floor measures one complete minimal hit, from canonical key to decoded document, without facade work. The facade work is the same in every path.

| Floor | Mechanism                                                                                                       |
| ----- | --------------------------------------------------------------------------------------------------------------- |
| F0    | `CacheCore.lookup_identity` with decoding, as in an independent manager. This is the reference.                 |
| F1    | Native shared-index lookup with validity checks, copy and decode, with the owner process alive and publishing.  |
| F2    | Native echo owner returning the entry over the Unix socket, for a synchronous caller and for an asyncio caller. |
| F3    | F2 with four selections per frame (asyncio caller, four in flight only).                                        |

CPU is the sum of user and system time of the caller and owner processes, divided by completed hits. Each floor uses five repetitions of 5,120 hits, sequentially and at four in flight. F3 runs only at four in flight, because a sequential caller has nothing to batch without delaying or prefetching requests. For each mechanism and caller, the larger of the sequential and four-in-flight medians is used. A family's added cost is that value minus the same caller's F0.

- **Margin.** 12.8 µs, half of the smallest v4 allowance (0.10 × 257 µs). The other half covers adapter, key-encoding and accounting work that the floor omits.
- **Eligibility.** A is eligible when F1 − F0 is within the margin. B serves both execution models, so each model must qualify on its own. B is eligible when both added costs are within the margin. For a synchronous caller, the cost is F2 − F0. For an asyncio caller, it is the larger of the sequential F2 − F0 and the four-in-flight min(F2, F3) − F0.
- **Order.** Build A if it is eligible. Build B only if A is ineligible, or if A stops for a reason B does not share (a failed safety scenario or the memory criterion). Build at most two full candidates.
- **No eligible family.** The study ends with the floor report and the [negative outcome](#outcome-handling).

### Shared index (candidate A)

**Ownership.** The owner process is the only writer, and `CacheCore` stays authoritative. The index is a projection: every published entry is a resident, valid `_id` identity entry within v4's prototype scope. A local miss falls back to v4's `select-identity` RPC, which may still hit an entry that is resident but not published. A local hit therefore never needs anything that the RPC path lacks. Correctness reduces to the requirements in [the delta spec](specs/shared-cache-benchmarking/spec.md).

**Memory.** The owner creates the index as one `memfd` (Linux) and maps it writable. Before any worker attaches, it applies `F_SEAL_FUTURE_WRITE`, `F_SEAL_GROW`, `F_SEAL_SHRINK` and `F_SEAL_SEAL`. The future-write seal is what stops modification: after it, no write and no new writable shared mapping succeeds through any descriptor, including one reopened through `/proc`, while the owner's earlier mapping stays writable. The grow and shrink seals only fix the size. The owner passes workers a read-only descriptor with `SCM_RIGHTS` during the [control handshake](#control-connection). A read-only descriptor alone would not be enough, because a same-user process can reopen a `memfd` read-write through `/proc`. Passing descriptors avoids the name exchange and resource-tracker problems that v4 recorded for named shared memory. The index has four parts:

- a header with the incarnation, and per database an availability word and the monotonic time of the latest completed upstream poll;
- a namespace table of epoch words;
- a fixed-capacity open-addressed slot table;
- a payload arena holding each entry's key bytes and BSON.

Each session's hit ring is a separate, unsealed `memfd`, passed only to that session's worker, so write access to a ring grants nothing over the index. The registration fixes the capacities, sized for the hot set at the group budget plus allocator overhead.

**Reads.** Each slot carries a 64-bit version, which is odd while being written. A worker reads the version with acquire ordering, then the slot fields, and bounds-checks the offset and length against the arena. It copies the key and payload, compares the key, and reads the version again. It accepts the copy only if both versions match and are even. A version check detects an inconsistent copy, but in Rust it does not make a concurrent plain read legal: overlapping plain accesses would be a data race and undefined behaviour before any retry. So every byte that the owner may rewrite while a worker reads it is accessed only through atomics. Slot fields are atomic words, and the key and payload are copied with relaxed atomic word loads, followed by an acquire fence before the second version read. Relaxed word loads compile to plain loads on x86-64, so F1 includes their cost. It also checks five things:

- that its attachment is live;
- that the header incarnation equals the attached incarnation;
- that the database's availability word is set;
- that the published progress is within the expiry;
- that the namespace epoch equals both the slot's epoch and the worker's metadata epoch.

After the registered number of version mismatches, the read counts as absent. Slot keys are the bytes from `wire.encode_key`, which owner and workers already share. The native code computes the hash.

**Writes.** The owner publishes through the [listener seam](#core-listener-seam) at the admission commit point: inside `_finalize_put`'s namespace section, after its validity check has passed. `record_write` runs under the same namespace lock, so an invalidation is ordered either before the commit, which then rolls back and publishes nothing, or after it, which then unpublishes the slot. Evictions are notified under the LRU lock. The writer marks each removed entry token as dead, and publishing a dead token does nothing, so an entry evicted between `conditional_put` and the commit is never published and its arena space is never referenced again. The owner writes slot fields and arena bytes with relaxed atomic stores, between an odd version and a release fence. Unpublishing makes the version odd, clears the slot, makes the version even with release ordering, and only then frees the arena space. A reader that copied reused space therefore always sees a changed version. No reader pins anything, so a paused or dead worker cannot hold up reclamation. A native mutex serializes the owner's writer threads (the RPC loop and stream supervisors). It is always the innermost lock.

**Invalidation mirroring.** A processed identity write unpublishes every slot of that identity. A namespace reset advances the namespace epoch word, and the core's removals then free the slots. Availability changes rewrite the availability word before the core's call returns. Each event therefore counts as processed only after the shared state reflects it, which keeps today's snapshot boundary.

**Fencing.** Progress words use the semantics of v4's `UpstreamProgress`: a completed `getMore`, including an empty batch, advances them, and a heartbeat thread cannot. Owner exit closes the worker's [control connection](#control-connection), whose only reader sets the worker's detached flag; every hit checks that flag. An owner that is paused but alive is caught only by the 3-second progress expiry. That is weaker than v4's 100 ms RPC deadline for a paused owner, but it equals the bound that v4 registered for silent faults. The report discloses it. Rejected alternatives: polling a `pidfd` on every hit (one syscall per hit), and robust futex ownership (more native complexity for the same EOF signal).

**Payloads stored once.** `CacheCore` gains an internal payload-store strategy with three operations: store an admitted payload, release it on removal, and take a snapshot for an encoded read. The default strategy keeps `bytes`, which are immutable, so its snapshot returns the same object. The owner's strategy keeps each payload only in the arena. An arena block carries its own version, which the writer advances before it frees or reuses the block. `lookup_identity_encoded` and `lookup_find_encoded` currently return `entry.value` after releasing their locks, and an eviction could then reuse the block before the RPC encodes its reply. So these reads return the strategy's snapshot instead. The owner's snapshot copies the block with the same atomic-copy and version check as worker reads, and a changed version makes the read a miss. That outcome is correct, because the entry was removed concurrently. Every owner RPC hit therefore pays one payload copy. That cost falls on fallback hits in A and on every hit in B, and the candidate measurements include it. The alternative, keeping the payload both in the core and in the arena, risks the four-worker memory criterion. An observer that swaps `CacheEntry.value` after admission would give the core's data an undeclared second writer. Unknown: whether the default strategy adds measurable cost to standalone hits. Task 2.2 resolves this with the performance guard. If it does, keep duplicate storage and record the memory risk in the registration before timing.

**Recency.** Workers append the slot tokens they hit to their session's ring. The owner drains the ring on its existing sweep and calls `WeightedLru.touch`. A full ring drops touches instead of blocking. Alternatives: a CLOCK bit in the slot would need the index to be writable by workers, which conflicts with the read-only requirement. Ignoring recency would quietly turn eviction into admission order, which the hot workload never exercises. The ring's cost is part of every measured hit.

### Control connection

Descriptors and liveness use one dedicated connection per worker attachment, separate from every RPC connection, in both execution models. That keeps the existing framed readers unchanged: `SyncEndpoint` reads thread-local connections with `recv()` and `AsyncEndpoint` reads through an asyncio `StreamReader`, and neither can see ancillary data. A second reader on an RPC socket could also consume reply bytes and break framing.

- **Handshake.** The worker connects a blocking socket and sends `hello` with role `control`. In asyncio workers this runs in `asyncio.to_thread`, before any stream owns the socket. The owner sends its reply frame with the index and ring descriptors attached to its first `sendmsg`; if that send is partial, the remaining bytes follow as ordinary data. The worker reads with `socket.recv_fds` and `MSG_CMSG_CLOEXEC`, accumulating bytes until exactly one frame is complete. It accepts descriptors only from that frame, and rejects the handshake if they are missing, repeated or of the wrong count.
- **Ownership.** The worker maps both descriptors and then closes them, because the mappings outlive their descriptors. On any handshake failure it closes every descriptor it received. The owner closes its copy of each ring descriptor after a successful send and keeps only its mappings.
- **Transition.** The owner never sends anything on a control connection after the handshake reply, so the frame reader cannot read past the handshake. After the handshake, a synchronous worker hands the socket to a daemon thread that blocks until EOF. An asyncio worker hands it to the loop with `asyncio.open_unix_connection(sock=...)` and runs one task that waits for EOF. In both cases that is the socket's only reader.
- **Sessions.** The control connection's session owns the ring. RPC connections keep v4's handshake and sessions and carry no descriptors.

### Core listener seam

`CacheCore` accepts an optional internal observer, `None` by default. It is notified of a committed admission (at the point described under **Writes**, never at LRU insertion), a residency removal (displacement, eviction, rollback, `remove_exact` or `clear_all`), an identity write, a namespace epoch change and an availability change. Each notification happens inside the lock section that makes the change. The observer must not call back into the core. The standalone cost is one `None` test per mutation and none per hit, and the existing pull request performance guard must not report a slowdown. Alternatives:

- subclassing `CacheCore` in the research owner, which duplicates every mutation path and drifts silently;
- wrapping the change-stream router, which misses evictions and admissions.

### Native extension

| Option                                    | Pros                                                                                                                                                     | Cons                                                                                             |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| Rust with PyO3, built by maturin (chosen) | Memory safety; standard atomics with explicit ordering; `loom` can model-check the version protocol; abi3 wheels for CPython 3.14 and newer if it ships. | Adds the Rust toolchain to contributor setup and CI.                                             |
| C extension on the CPython API            | Needs only a C compiler; C11 atomics.                                                                                                                    | Manual reference counting and bounds safety in exactly the code where mistakes serve wrong data. |
| Cython                                    | Python-like source.                                                                                                                                      | Atomics and memory ordering need C escapes, so it gains nothing over C for this code.            |
| cffi with C                               | No CPython API.                                                                                                                                          | Call overhead per hit lands in the cost being minimized.                                         |

Unknowns: PyO3's per-call overhead on CPython 3.14 (F1 measures it), and abi3 support for the project's Python range (task 1.2 checks it when creating the crate). The crate verifies its version protocol and reclamation with `loom` model tests and its safe API with ordinary `cargo test`.

**Packaging.** The crate is a separate maturin distribution, `client-query-cache-shared-index`, at `native/shared-index/`. It is a uv workspace member listed in the `dev` group and is never a runtime dependency. The published wheel stays pure Python from `uv_build`. Alternatives:

- switching the main build to maturin, which would make every wheel platform-specific before any mode is supported;
- a separate repository, which makes the measured source harder to pin and reproduce;
- building outside the lock, which leaves the measurement unreproducible.

**Toolchain.** The dev container installs Fedora's `rust` and `cargo` through DNF, unpinned under the existing DNF policy. CI uses the runner image's preinstalled stable toolchain. The crate declares `rust-version` as a compatibility declaration. `Cargo.lock` is committed and owned by a Dependabot `cargo` entry. The report records the `rustc`, maturin and crate versions that it measured.

### Candidate B, if built

A native thread in the owner accepts worker connections, answers `select-identity` hits from the candidate A index under the same validity checks, and hands every other frame to the Python owner loop. Workers keep v4's attachment and deadline. The batching variant applies only if F3 made B eligible.

### Registration version 5

`reports/shared-worker-cache/v5/` reuses v4's workload, data, partitioned keys, phases, counterbalancing, estimands, inference, bounds and gate. The v4 registration stays the source for all of these. Version 5 differs in these ways:

- **Paths.** `direct`, `independent` and each built candidate (`shared-index`, `shared-native-rpc`). v4's `shared` path already stopped and is not repeated.
- **Calibration.** Fresh baseline-only calibration under v4's rule, because the harness revision changes.
- **New bounds.** Owner-exit detection within 100 ms, local read retries, slot and arena capacities and hit-ring capacity.
- **Integration criterion.** v4's "one cache algorithm/router" becomes: "`CacheCore` remains the authority for admission, eviction and generations; published state serves only what the core would serve, enforced by the differential check." Direction A cannot avoid a local validity check. The amended wording keeps the property behind v4's rule, which is no divergent admission or eviction policy, and makes it testable.
- **Fault cases.** In addition to v4's cases: owner SIGKILL and SIGSTOP during local hits, torn-read stress under publication churn, and reattachment after restart.
- **Intervals.** With two candidates, v4's 97.5% interval rule applies.

### Outcome handling

v4's [outcome handling](../archive/2026-10-10-investigate-shared-worker-cache/design.md#outcome-handling) applies, with these specifics:

- **No candidate built.** The crate and floor programs stay as research sources outside the `dev` group. Drop the development-environment delta and the toolchain changes. The report gives the cargo-based reproduction commands.
- **Negative verdict after candidates ran.** Publish a permanent tag for the measured source and verify the smoke run from a clean detached worktree at that tag. Then remove the crate, the candidate adapters, the toolchain changes and the development-environment delta. Also remove the core seams, unless another use justifies them. Rust should not remain a contributor requirement for research that failed.
- **Passing verdict.** Everything stays, and the report opens the integration issue that the non-goals defer.

In every case, the [research report](../../../docs/development/research/shared-worker-cache-feasibility.md) gains a version 5 section with the floors, the verdict, the bottleneck and the reproduction commands. Issue #229 closes only on a passing verdict.

## Risks / Trade-offs

- [A memory-ordering or bounds bug serves wrong data] → `loom` model tests, the differential check, a multi-process torn-read stress test and native bounds checks before any timing. Safety failures stop a candidate regardless of numbers.
- [PyO3 call overhead dominates a local hit] → F1 measures it before any full build.
- [The listener or payload seam slows standalone hits] → performance guard, with duplicate storage as the fallback.
- [A paused owner keeps stale entries servable for up to 3 s] → this equals v4's registered expiry for silent faults, and the report discloses it. A passing study does not by itself settle whether that bound is acceptable for a supported mode.
- [Rust becomes a contributor burden] → only while the extension is in the tree. Outcome handling removes it after a negative verdict.
- [Weak memory ordering is validated only by model checking] → the measured host is x86-64. The report states that ARM evidence is limited to `loom`.
- [The harness generalization in `benchmark-concurrent-worker-workload` is not merged yet] → registration tasks stop and report the blocker. Floors and the prototype do not depend on it.
- [Eight-worker cells sit near host saturation] → same limitation as v4, stated in the report.

## Migration Plan

Not applicable. This change ships no supported behaviour, and the published package is unchanged.
