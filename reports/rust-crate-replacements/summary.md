# Rust crate replacements

Evaluation of the focused dependency substitutions planned for the native extension. Each candidate is judged against its predecessor build; the final combination is compared with frozen `main`.

## Baseline

- Frozen `main`: `ca5cf25b4610d6b726a5d572e52d0c0db98eefdd`.
- Host: 4 vCPUs and 15 GiB in a shared cloud container (Linux 6.18), rustc 1.100.0, CPython from `uv python find`; children pinned to CPU 2 with address-space randomization off.
- Screening builds: `cargo build --release --locked --features python` (fat LTO, one code-generation unit, no PGO) in a separate target directory per variant, overlaid onto a copy of the package with an equal-length path per label. A shared target directory let Cargo reuse one variant's fingerprints for another, so its binaries could not be tied to their source and the first 1a screening was discarded. Clean builds in fresh target directories reproduced their earlier digests, while an incremental rebuild of `main` in a reused directory produced a different extension (`c6ec0195…` against the clean `b742f9a6…`). Confirmations therefore use clean builds of both sides; because clean builds reproduced byte for byte, they showed no same-source build variation for unprofiled screening builds. Release-wheel claims additionally need independently PGO-trained builds.

## Comparison family

Each row is one performance comparison whose metric is the median nanoseconds per operation of the named workload in `research.native_build_profile.measure`, unless stated otherwise. Every metric calls the affected native entry point directly; integrated workloads such as `wire_keys` and `facade_find_miss` serve only as regression controls and cannot qualify a candidate. The family's 5% error budget is split by Bonferroni over its 16 comparisons: α = 0.003125 each, so confirmation intervals use 99.6875% confidence (`--confidence 0.996875`). Alternatives found later stay exploratory.

| ID  | Candidate | Variant                                                   | Metric                   |
| --- | --------- | --------------------------------------------------------- | ------------------------ |
| F1  | 1a        | `itoa` for tuple indexes in `key_encoder.rs`              | `find_key_encoding`      |
| F2  | 1a        | Shared handwritten decimal for tuple indexes              | `find_key_encoding`      |
| F3  | 1a        | `itoa` for `array.rs::decimal`                            | `capture_array`          |
| F4  | 1b        | `FxBuildHasher` for `Writer::published`                   | `shared_publish_cycle`   |
| F5  | 1b        | `FxBuildHasher` for integer-keyed `Residency` collections | `owner_admission`        |
| F6  | 1b        | `FxBuildHasher` for integer-keyed `Residency` collections | `shared_publish_cycle`   |
| F7  | 2a        | `rapidhash` for `hash.rs::key`                            | `shared_hit_small`       |
| F8  | 2a        | `rapidhash` for `hash.rs::key`                            | `shared_publish_cycle`   |
| F9  | 2b        | `hashbrown` table, unchanged hashers                      | `identity_hit_small`     |
| F10 | 2b        | Keyed scoped hash, pass-through standard map hasher       | `identity_hit_small`     |
| F11 | 2b        | Keyed scoped hash, pass-through standard map hasher       | `admit_churn_small`      |
| F12 | 2b        | Keyed scoped hash, `hashbrown::HashTable`                 | `identity_hit_small`     |
| F13 | 3a        | `hashlink` for `Probes`                                   | Owner-contention reads/s |
| F14 | 3b        | `slab` for `Slots<T>`                                     | `admit_churn_small`      |
| F15 | 4a        | `smallvec` for `Sizer::pending`                           | `limited_unique_single`  |
| F16 | 4b        | `parking_lot` for an eligible lock                        | Owner-contention reads/s |

Maintenance-based decisions do not belong to this family and claim no speedup.

### Registration revision

A first registration measured F1 and F2 by `wire_keys`. Its screening showed that `KeyCache` serves repeated families from its own cache, so the workload rarely reaches tuple-index formatting, and its A/A spread (up to ±15%) hides the operation. Before any other candidate was measured, the family was re-registered with the metrics above, and that screening became the pilot allowed by the duration rule. Pilot observations select neither the confirmation sample nor its data; confirmations use only fresh rounds.

### Second looks

The second confirmations of F5, F7 and F8 were registered after their first confirmations had already been tested at α = 0.003125, so they are not a prespecified sequential design: each of these comparisons spent 0.003125 + 0.0016 ≈ 0.0047, and the family's error bound is about 5.5% rather than 5%. The qualifying results are far below either level: F7 was faster in 20 of 20 rounds (two-sided sign-test p ≈ 2 × 10⁻⁶) and F8 in 18 of 20 (p ≈ 4 × 10⁻⁴); F5 failed.

## Duration rationale

The decision for each comparison is whether a reproducible positive effect exists at the registered metric. A 3-round smoke A/A of seven workloads took 31.7 s (projected 30.9 s) with valid outcomes, which bounds per-workload cost at roughly 0.7 s per build and round. Each screening therefore alternates `base`, an identical-binary A/A copy and the candidate over only its registered workloads plus the integrated controls it affects.

A 7-round A/A pilot over the registered workloads first failed: the identical copy was slower in six of seven rounds regardless of order (geometric mean −6.6% [−9.1, −5.1]). With address-space randomization off, each file copy kept its own page-cache pages, which pinned a different physical layout to each label. `compare.py` now rewrites every extension as a new file before each child run, turning that bias into round-to-round noise; the repeated pilot centered at +0.8% [−1.2, +2.4] with about ±5% per workload.

Two further control failures changed the acquisition before candidate 1b. Bursts of host interference lasting seconds inflated whole workload medians (the worst per-round A/A difference reached 70%) while minima stayed flat, and local processes, including the agent's own tools, could run on the measured CPU. From 1b onward every acquisition moves all other processes off CPU 2 (`taskset -a -p -c 0,1,3` for each process) and compares the 10th-percentile batch (`--statistic p10_ns`), chosen from A/A spreads alone. The repeated A/A then stayed within ±3% per workload (−0.6% geometric mean). Earlier 1a results use medians without CPU isolation.

- Screening: 7 rounds, the existing runner default, exploratory 95% intervals.
- Confirmation: 10 fresh rounds with independently rebuilt binaries. At the allocated confidence a percentile interval over 10 paired rounds excludes zero only when essentially every round favors the candidate, which matches a sign test (2⁻¹⁰ ≈ 0.001 < α); fewer rounds cannot reach α, more would only narrow an interval once the sign is settled.
- Compilation is reported apart from acquisition: a clean unprofiled release build took about 28 s and a PGO-trained release wheel (`just build`, three compilations plus training) about 86 s. No measurement was repeated because of a rebuild.
- Timeout: twice the projection from the first round; a timeout yields an explicit incomplete result.

## Candidate decisions

### 1a: decimal formatting

**Tuple indexes (`key_encoder.rs`): adopted `itoa` 1.0.19 (F1).** Formatting each tuple element's index with `to_string()` allocated a string per element. On `find_key_encoding` (eight canonical filters with a 256-element `$in`), screening gave +20.5% [+18.7, +22.1] for F1 and +11.7% [+9.6, +15.5] for F2, the dependency-free reuse of `array.rs::decimal`, against an A/A of +0.6%. Confirmation on 10 fresh rounds of clean, independent builds gave F1 +21.2% [+19.5, +23.2] at 99.6875% confidence (A/A −0.1%). Integrated controls: `wire_keys` +3.2% [+0.8, +9.6], `facade_find_miss` −0.7% [−4.2, +2.5]; the facade's own key cache hides most of the gain. The claim is bounded to encoding uncached find families; F2 was not confirmed because F1 won its screening. `itoa` is enabled only with the `python` feature and passes `cargo deny` (advisories, bans, licenses, sources).

**Array indexes (`array.rs::decimal`): rejected `itoa` (F3).** Against the F1 build, screening gave `capture_array` +5.5% [+4.4, +9.1] with an A/A of +3.4% [−0.9, +8.3]; confirmation on 10 fresh rounds gave +2.6% [−3.0, +17.4] at 99.6875% confidence (A/A +1.7%), so the performance effect is inconclusive. An unrelated workload moved by −5.8% when only this site changed in the first screening, which shows the layout sensitivity behind such results. On maintenance, the crate would remove a 12-line allocation-free loop with no coordinated state, but `array.rs` is compiled in every build, so `itoa` would become a dependency of the default-feature and Loom builds as well. The handwritten function stays, now tested against standard formatting at every power-of-ten boundary up to `u64::MAX`.

### 1b: `rustc-hash` for internal integer keys

Pre-registered before acquisition: a second F5 confirmation on 20 fresh rounds, tested at α = 0.0016, qualifies only if F5's `owner_admission` p10 is below the predecessor's in at least 18 of 20 rounds (two-sided sign-test p ≈ 0.0004).

The keys of `Writer::published` are writer tokens, a version counter above an arena offset, and every integer key of `Residency` (namespace ids, row and identity slots, index tokens, and the row sets) is assigned internally, so no caller chooses them; the string-keyed database maps keep SipHash.

**`Writer::published`: rejected (F4).** Screening gave `shared_publish_cycle` +0.6% [−2.8, +2.1] (A/A −1.3%). `index.rs` is compiled without `python`, so the change would also have made `rustc-hash` a dependency of every build.

**`Residency`: rejected (F5, F6).** Screening gave `owner_admission` +3.0% [−0.2, +4.9] and `shared_publish_cycle` +1.9% [−0.9, +2.6]. The first confirmation (10 rounds) gave `owner_admission` +5.5% [+2.2, +10.7] at 99.6875% with an A/A of +2.9% [−3.0, +6.3], but F5 was faster than the predecessor in only 9 of 10 rounds and faster than both copies in 6 of 10, which does not meet the sign criterion. The second confirmation gave +1.8% [−2.4, +8.6] with F5 faster in 13 of 20 rounds against 11 of 20 for the A/A copy, below the registered 18. Any remaining effect is smaller than this host can resolve.

### 2a: `rapidhash` for the shared index key

Pre-registered before acquisition: the first confirmation lost two of ten rounds to host bursts, so a second confirmation on 20 fresh rounds runs each label twice per round and keeps each workload's faster run (`--repeats 2`), is tested at α = 0.0016, and qualifies F7 or F8 only if the candidate's p10 is below the predecessor's in at least 18 of 20 rounds on `shared_hit_small` (F7) or `shared_publish_cycle` (F8).

**Adopted `rapidhash` 4.5.1 (F7, F8).** The handwritten mixer folded the namespace and each key field into one serial multiply chain, eight bytes at a time; shared find keys carry a 460-byte shape. The replacement hashes the identity with the portable v3 algorithm, seeded from a fixed secret and the namespace, then hashes the shape seeded with that result. Each call mixes its own input length into its hash, which separates field boundaries without concatenating (with high probability, as for any 64-bit hash), and v3 reads little-endian words, so owner and readers agree. The changed mapping raised the index layout version to 4; mappings of other versions are refused, and a pinned known key fails the tests if a crate update changes the output.

Screening: `shared_hit_small` +25.0% [+20.5, +25.1], `shared_hit_medium` +20.0%, `shared_miss` +42.6%, `shared_publish_cycle` +3.0% [+1.2, +6.8] (A/A within ±4.2%); every lookup returned its expected hit or miss under both builds. The first confirmation lost two of ten rounds to host bursts (F7 faster in 8 of 10). The pre-registered second confirmation gave `shared_hit_small` +25.3% [+23.6, +26.3], faster in 20 of 20 rounds, and `shared_publish_cycle` +4.2% [+1.5, +5.9], faster in 18 of 20, against 10 and 11 of 20 for the A/A copy, which meets both criteria. Owner admission did not change (+0.4%). The collision test's full 64-bit collisions were found again for the new mapping by Pollard-rho searches (about one minute each on one core): one pair of 16-byte identities with eight leading zero bytes, and one pair colliding an 8-byte with a 16-byte identity, which keeps the earlier unequal-length case.

### 2b: scoped hash and process-local index table

`scoped_hash` hashed the namespace, kind and Python hashes with a zero-key SipHash (`DefaultHasher::new()`), and `State::index` hashed that result again with a randomized `RandomState`.

**Table only: rejected without a prototype (F9).** The standard `HashMap` is hashbrown's SwissTable, so the `hashbrown` crate with the same hashers runs the same algorithm and adds only a dependency.

**Keyed scoped hash with a pass-through table: adopted (F10, F11).** Each process-local core now holds one randomized SipHash key and hashes the scope once; the index map takes that value unchanged. The second hash disappears, and full 64-bit collisions of scoped hashes can no longer be computed in advance from public keys. The pass-through hasher implements only `write`, so every line is reachable through the standard `write_u64`. Screening gave `identity_hit_small` +1.0% [−1.3, +3.5], `admit_churn_small` +3.8% [−2.0, +5.7] and an unregistered `find_exact_hit` +7.0% (A/A within ±2.1%). Confirmation (10 rounds, two runs per build per round) gave `admit_churn_small` +4.2% [+2.6, +9.5] at 99.6875%, faster in 10 of 10 rounds against 5 of 10 for the A/A copy, which qualifies F11; `identity_hit_small` −0.2% [−1.4, +1.8] (5 of 10) does not qualify F10. `find_exact_hit` +6.4% remains exploratory. The integrated hasher measured within noise of the confirmed build (`admit_churn_small` −0.1% [−4.5, +2.9]).

**Keyed scoped hash with `hashbrown::HashTable`: rejected (F12).** It removes the adapter but adds a dependency, and its screening (`identity_hit_small` +2.3% [−3.0, +3.7]) showed no advantage over F10.

### 3a: `hashlink` for metadata probes

**Rejected (F13).** With a fixed TTL and a monotonic clock, expiry order equals refresh order, so a `LinkedHashMap` (with `RandomState`, because namespace names are caller-chosen) could replace the `BTreeMap`, both sequence counters and the cloned names it held: the prototype removed 9 net lines. It would add `hashlink`, `hashbrown` and `foldhash`. A native test with an explicit clock checks the invariant either way: a refreshed probe must outlive an older probe whose TTL expired, and it fails when a refresh does not move the probe to the back.

The probes run under the owner state mutex. The extension is an `abi3` module, which free-threaded CPython cannot load, so every owner call holds the GIL and added protected work appears as serialized per-call cost. The focused control ran probe refresh and completion at a matched 1,000 cycles/s beside closed-loop owner admissions on the same owner (10 rounds, 3 s each): admissions/s −1.0% for F13 against +1.6% for the A/A copy, p99 −3.7% against +2.8%, all within a ±15% round spread. At that load probing occupies about 0.4% of the owner's time, so the per-probe change cannot materially affect contention.

The held-out `metadata_probe_cycle` workload improved by +18.3% [+17.1, +21.9] (exploratory: the registered F13 metric is the contention control). Owner admission, which never touches the probes, was slower in both acquisitions: −3.0% [−3.3, −2.2] in screening and −4.2% [−9.0, +3.2] in confirmation, slower in 7 of 10 rounds against 3 of 10 for the A/A copy. The likely cause is code layout in the single-unit LTO build, which this change cannot correct; with a maintenance-only benefit on a cold path, the reproducible adverse signal and three new crates outweigh the simplification.

### 3b: `slab` for row and identity storage

**Adopted `slab` 0.4.12 on maintenance grounds.** `Slots<T>` threaded a free list through 64-slot boxed chunks with its own vacant/occupied enum, indexing and count. `Slab` provides the same reusable integer storage; the remaining adapter maps one-based handles to keys, takes a reservation with `vacant_key()` and asserts that the install receives that key (nothing reserves twice from one store before installing), and replaces the store when it empties because `Slab::clear` keeps its capacity. Stale-reference tokens remain in the handles and are unchanged. The change removes 46 net lines.

Storage at equal residency (all lookups hit; five alternating runs each):

| Entries | Build  | Filled RSS (KiB) | RSS after draining (KiB) |
| ------- | ------ | ---------------: | -----------------------: |
| 1,000   | chunks |          720–748 |                  900–928 |
| 1,000   | `slab` |          792–860 |                  872–940 |
| 100,000 | chunks |    74,444–74,456 |            26,012–27,256 |
| 100,000 | `slab` |    75,072–75,192 |              5,044–6,312 |

The slab grows by doubling, so a filled cache holds up to about 1% more at 100,000 entries and 60–120 KiB more at 1,000; this trade-off was accepted as immaterial. After draining, freed chunks stayed in the allocator's heap while the slab's single large buffer returned to the operating system. The slowest single admission while filling 100,000 entries measured 67–105 ms for both builds.

The final release wheels raised the peak RSS of the combined native measurement process by a median 4.6% (86.7 MiB to 90.2 MiB on unprofiled builds just before and after this change), so the decision was revisited with the maintainer: keep the slab if the extra memory stays within about 5% of the process peak, including at a capacity-doubling boundary. Filling 65,536 and 65,537 entries (three alternating runs each) gave:

| Build  | Filled RSS (KiB) | Process peak RSS (KiB) | Slowest admission (ms) |
| ------ | ---------------: | ---------------------: | ---------------------: |
| chunks |    50,196–50,368 |        145,688–146,412 |                3.0–9.8 |
| `slab` |    51,140–51,252 |        146,984–147,224 |                2.9–4.4 |

The slab adds about 1.9% filled and 0.7% process peak, with no growth spike and no admission outlier: a mapped buffer grows by remapping rather than copying, and its untouched new capacity is not resident. The slab is retained on maintenance grounds; no performance gain is claimed for it.

Screening gave `admit_churn_small` +2.5% [+0.4, +3.7], `write_invalidation` +3.6%, `namespace_lifecycle` +11.2% (A/A within ±1.8%). Confirmation gave `admit_churn_small` +1.8% [−0.8, +2.9], faster in 7 of 10 rounds against 5 of 10 for the A/A copy, so no performance claim qualifies (F14); the `namespace_lifecycle` gain (+10.1% [+8.3, +11.7]) remains exploratory. No control regressed beyond the A/A range in either acquisition.

### 4a: `smallvec` for key sizing

**Rejected (F15).** A `Sizer` is built per decision, so `pending` allocated `KEY_NODES` (32) entries on every call. A throwaway instrumented build recorded each decision's peak `pending` length: across the key-limited training workloads (206,337 decisions) the peak never exceeded 15 (median 8), and across `tests/core/test_retention_limits.py` (346 decisions) the median was 2, p99 5 and the maximum 55. An inline capacity of 16 covers every workload decision and 99.7% of the test keys. Against the slab build, screening gave `limited_unique_single` −1.7% [−3.6, +1.9], `limited_namespace_pressure` −3.6% [−4.3, −1.8] and `limited_unique_pair` −3.3% [−4.5, −2.9] (A/A within ±1.7%): the larger frame and branching cost more than the allocation even when every key fits inline, so spilling keys were not measured. The vector stays, and `Pins` and `MetaPins` were left alone.

### 4b: `parking_lot` for process-local locks

**Rejected for every lock (F16).**

- The `State` mutex of the process-local core and its capture and identity owners `expect` a healthy lock on every acquisition, so a panic inside a critical section fails every later call. `parking_lot` has no poisoning; keeping that behaviour would need a custom poisoning layer, so this lock was rejected without a prototype.
- `OwnerIndex::writer`, the session ring's admission queue and descriptor, and `EncodedArray`'s builder already recover poisoned locks with `PoisonError::into_inner`, which `parking_lot` matches. No binding releases the GIL and these locks are per process, so they are never contended; only their uncontended cost can change, and both implementations take one atomic compare-and-swap. Screening the prototype gave `admission_queue` +5.0% [+2.3, +5.8] (exploratory), `shared_touch` −2.4% [−5.1, −1.0], `capture_array` −0.2%, `shared_publish_cycle` −0.6% and `owner_admission` −1.9% (geometric mean +0.1%; A/A within ±0.8%). Removing seven poison recoveries does not justify `parking_lot`, `parking_lot_core`, `lock_api`, `scopeguard` and their platform dependencies, and the shared-touch regression weighs against it.

## Combined release build

The branch's integrated native code was compared with frozen `main` as PGO-trained release wheels from `just build`: two independently trained wheels per source, unpacked into equal-length overlays with an identical copy of the first `main` wheel as the A/A control. Ten rounds, two runs per wheel per round, `p10_ns`, startup imports measured after the rounds; 838 s against a projected 867 s. Values are improvements against the first `main` wheel; the second `main` wheel shows rebuild and training variation.

| Workload               |  A/A | `main` B | Branch A | Branch B |
| ---------------------- | ---: | -------: | -------: | -------: |
| `admit_churn_small`    | −0.6 |     −0.4 |     +2.5 |     +1.0 |
| `facade_find_miss`     | −0.6 |     −1.7 |     +2.1 |     +1.7 |
| `facade_hit`           | +0.0 |     −2.5 |     +1.4 |     −1.1 |
| `find_exact_hit`       | −0.5 |     −0.7 |     +2.8 |     +4.0 |
| `find_key_encoding`    | −1.7 |     −9.0 |    +19.4 |    +21.1 |
| `identity_hit_small`   | −1.2 |     +1.2 |     +2.1 |     +2.5 |
| `namespace_lifecycle`  | −1.6 |     +1.4 |    +18.2 |    +15.7 |
| `owner_admission`      | −0.6 |     +2.4 |     +6.4 |    +12.5 |
| `shared_hit_small`     | −1.3 |     −1.5 |    +29.8 |    +30.0 |
| `shared_publish_cycle` | −0.0 |     −0.3 |     +4.3 |     +4.5 |
| `write_invalidation`   | −0.6 |     −0.5 |     +5.2 |     +2.2 |
| Geometric mean         | −0.3 |     −1.6 |     +8.9 |     +8.6 |

Against each `main` wheel separately, both branch wheels were faster in every round on `shared_hit_small`, `find_key_encoding`, `namespace_lifecycle` and `find_exact_hit`. `facade_hit` (−1.1% for one branch wheel, 21 of 40 paired rounds faster) stays within the −2.5% spread between the two `main` wheels, so no path regressed. These are native call sequences; the Python facade and PyMongo bound the gain of complete cached reads, which was not measured.

Resources: startup import 236.5 and 240.6 ms against 242.7 and 245.7 ms for `main` (A/A 234.9 ms); extension 1,152,288 and 1,139,336 bytes against 1,149,720 and 1,163,400. The measurement process's per-round peak RSS (the larger of each round's two runs) rose by a median 4.6% for both branch wheels (A/A −0.06%, second `main` wheel +0.07%), and its largest single peaks were 87,140 and 87,860 KiB against 83,228–83,464 KiB for `main` (+4.4% to +5.6%); this is attributed to the slab and accepted as recorded above. Unchanged `main` unit tests (`tests/core`, `tests/shared_cache`, 1,611 tests) passed on the branch wheel in 14.84 s against 14.79 s on the `main` wheel; the added tests are new cases and have no baseline.

## Complete cached reads

Both end-to-end harnesses ran on the same four release wheels against disposable MongoDB replica sets in Docker.

Process-local reads used `research.native_build_profile.end_to_end` (the pull-request guard workload: sync and async hits with and without telemetry, `find()` admission and invalidation, small and medium documents), 7 rounds of 3 runs keeping the fastest. Against the first `main` wheel, the geometric mean was +1.1% [−3.2, +4.0] and +0.7% [−1.0, +2.5] for the two branch wheels and +1.2% [−0.8, +4.4] for the second `main` wheel; every cell stayed within that rebuild spread. The process-local changes (keyed scope hash, slab) save tens of nanoseconds per call, below this workload's resolution.

Shared reads used `benchmarks.public_shared_cache --validate --disable-telemetry --paths shared --workloads hot` (four workers, 4,096 hot identities, about 4 KiB documents, three repetitions per run), 6 counterbalanced rounds per wheel, each wheel installed in its own virtual environment. Every window validated its installed implementation and completed 8,000 reads. Median latency improved by +0.4% to +3.0% (sync) and +0.5% to +12.4% (async) across the four branch-to-`main` pairs, with the branch faster in only 3 or 4 of 6 rounds, against a rebuild spread of +1.9% and −0.8%; p99 and throughput were equally mixed. The native lookup saving (about 570 to 430 ns) is about 2% of a 6.5 µs shared read, which this host cannot resolve, so no complete-read latency gain is claimed.

Each wheel was installed with `uv venv` and `uv pip install` into its own virtual environment, and the harness ran with that environment's Python.

## Outcome

Adopted: `itoa` for tuple-index formatting (1a), `rapidhash` for the shared index key (2a), a keyed scoped hash with a pass-through index map (2b) and `slab` for row and identity storage (3b, maintenance). Rejected: `itoa` for array indexes, `rustc-hash` for internal integer keys, `hashbrown`, `hashlink`, `smallvec` and `parking_lot`.

## Reproduction

Rebuild the compared source as described under Baseline: one clean target directory per variant, `RUSTFLAGS="--remap-path-prefix=<checkout>=/src"`, `cargo build --release --locked --features python`, and the extension copied over a package copy in an equal-length overlay. Release wheels come from `just build`. Rejected candidates are reconstructed from the integrated branch by the stated substitution: add the named crate and replace the named structure, keeping its existing tests. Then, with all other processes moved off CPU 2:

```bash
uv run python -m research.native_build_profile.compare --overlay-root <overlays> --baseline <predecessor> --labels <aa-copy> <candidate> --rounds 10 --repeats 2 --cpu 2 --statistic p10_ns --confidence 0.996875 --workloads <registered metric and controls> --output <untracked>.json
```

The full-hash collision pairs in `native/shared-index/src/index/tests.rs` were found with Floyd's cycle search over a function mapping a 64-bit value to an identity (its eight little-endian bytes when even, the same bytes after eight zero bytes when odd) and then to `hash::key(1, identity, b"find_one")`: iterate from a start until tortoise and hare meet, walk from the start and the meeting point together until their successors match, and keep the pair when the two predecessors differ (and, for unequal lengths, differ in parity). Each search takes about one minute on one core.
