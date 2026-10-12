# Shared worker cache registration, version 5

Version 5 asks whether a shared worker cache that avoids the owner round trip on hits can pass the [version 4](../v4/registration.md) gate. It reuses version 4's workload, data, phases, counterbalancing, estimands, inference, bounds and gate; version 4 stays their source. The [design](../../../openspec/changes/reduce-shared-cache-overhead/design.md) records the rationale for every difference.

**Status:** frozen. The machine-readable values live in [config.json](config.json). The candidate selection rule was registered before any floor was measured, and the paths, bounds, integration criterion, fault cases and reproduction commands below before baseline calibration. The frozen `config.json` has SHA-256 `57f4fcce3a96b6a04d0d0020f270411875806971126ecb2298bdc80e49df7580`, which every candidate report must carry. Any change to this file or `config.json` after a candidate measurement starts requires a new registration version and fresh affected comparisons; earlier outcomes are retained.

## Candidate selection

The study builds at most two full candidates, chosen by exploratory per-hit cost floors. Floors select the experiment order only; they are excluded from every gate and cannot support promotion.

| Family | Candidate                                                                                                                  |
| ------ | -------------------------------------------------------------------------------------------------------------------------- |
| A      | Shared index: the owner publishes identity entries and validity words into read-only shared memory, and workers read them. |
| B      | Native owner hot path: a native owner thread answers identity selections from the same index over the Unix socket.         |

Batching several selections per frame is a variant of B, measured by floor F3.

### Floors

| Floor | Mechanism                                                                                                               |
| ----- | ----------------------------------------------------------------------------------------------------------------------- |
| F0    | `CacheCore.lookup_identity` with decoding, as in an independent manager. This is the reference.                         |
| F1    | Native shared-index lookup with validity checks, copy, hit-ring append and decode, with the owner process alive.        |
| F2    | Native echo owner returning the entry over a Unix-domain socket.                                                        |
| F3    | F2 with up to four selections per frame: an asyncio caller coalesces the selections issued in one event-loop iteration. |

- **Entries.** The 16,384 `primary` documents from seed 197, encoded with the core codec and all resident: F0 in a `CacheCore` with version 4's 96 MiB budget, F1–F3 in the floor prototype.
- **Hit.** One hit starts from the `_id` value and the `find_one` read shape and ends with the decoded document, without facade work. F0 calls `CacheCore.lookup_identity`. F1–F3 encode the canonical identity with `wire.encode_key` and take the shape bytes from a key cache, as the research adapters do.
- **Floor prototype.** The `client-query-cache-shared-index` crate holds the entries in a preallocated fixed-slot table and payload arena in an anonymous shared mapping, which the owner process inherits through `fork`. A read takes the slot version with acquire ordering, accesses every byte the owner may rewrite only through atomic loads, bounds-checks the entry against the arena, and accepts the copy only when the version is unchanged and even. It also checks that the attachment is live, that the header incarnation equals the attached incarnation, that the database's availability word is set, that the published progress is within version 4's 3-second expiry, and that the namespace epoch equals both the slot's epoch and the caller's metadata epoch. Only F1 appends the hit's slot token to a hit ring.
- **Owner process.** F1–F3 share one owner process. It publishes the entries, then every 50 ms (version 4's owner sweep interval) advances the database's progress word and discards the hit-ring tokens, so no append is dropped. Its native echo thread serves F2 and F3 from one `epoll` loop and reads entries through the same read path. F0 has no owner.
- **Callers.** A synchronous caller runs one thread (sequential) or four threads (four in flight); in F2 each thread has its own connection. An asyncio caller runs one task (sequential) or four tasks (four in flight) on one event loop; in F2 and F3 the tasks share one connection and match replies by request id. F3 runs only at four in flight, because a sequential caller has nothing to batch without delaying or prefetching requests.
- **Repetitions.** For each floor, caller and mode: one untimed warm-up of 5,120 hits, then five timed repetitions of 5,120 hits. Repetition `r` draws its keys from the seeded permutation `r` of all 16,384 keys. Repetitions are interleaved: every floor, caller and mode completes repetition `r` before any starts repetition `r + 1`.
- **CPU.** User plus system time from `getrusage(RUSAGE_SELF)` of the caller process and of the owner process, taken around each repetition and divided by its completed hits. `getrusage` reports microseconds, whereas `os.times()` reports whole clock ticks of 10 ms on the test host.

### Rule

For each floor and caller, the statistic is the larger of the sequential and four-in-flight medians of CPU per hit. A family's added cost is that statistic minus the same caller's F0 statistic.

- **Margin.** 12.8 µs, half of the smallest version 4 allowance (0.10 × 257 µs of total CPU per request). The other half covers adapter, key-encoding and accounting work that the floors omit.
- **Eligibility.** A is eligible when F1 − F0 is within the margin for both callers. B is eligible when both callers qualify: the synchronous caller with F2 − F0, and the asyncio caller with the larger of the sequential F2 − F0 and the four-in-flight min(F2, F3) − F0.
- **Order.** Build A if it is eligible. Build B only if A is ineligible, or if A stops for a reason B does not share: a failed safety scenario or the memory criterion. B includes asyncio batching only when the asyncio caller qualifies through F3 alone.
- **No eligible family.** The study ends with the floor report and builds no candidate.

### Floor results

Measured on the test host (Intel Core i3-13100, Linux 7.2.9, CPython 3.14.7, PyMongo 4.18.2) at revision `eadca6fe62412d8f998b0de4fda02d3bf18e63f7` with rustc 1.95.0, maturin 1.15.0 and PyO3 0.29.3, building one `cp314-abi3` wheel. Values are caller plus owner CPU per hit in µs over the five timed repetitions; the owner column is the median owner part. Every read hit, and the hit ring dropped no token.

| Floor | Caller      | Mode           | Median |       Range | Owner |
| ----- | ----------- | -------------- | -----: | ----------: | ----: |
| F0    | synchronous | sequential     |  11.30 | 11.00–11.47 |     – |
| F0    | synchronous | four in flight |  12.41 | 11.17–12.90 |     – |
| F0    | asyncio     | sequential     |  11.36 | 10.98–11.80 |     – |
| F0    | asyncio     | four in flight |  10.80 | 10.53–10.92 |     – |
| F1    | synchronous | sequential     |   5.76 |   5.61–6.01 |  0.02 |
| F1    | synchronous | four in flight |   6.87 |   5.88–7.79 |  0.02 |
| F1    | asyncio     | sequential     |   6.53 |   6.09–7.32 |  0.02 |
| F1    | asyncio     | four in flight |   5.87 |   5.70–5.98 |  0.01 |
| F2    | synchronous | sequential     |  14.25 | 13.95–14.74 |  4.99 |
| F2    | synchronous | four in flight |  24.76 | 24.31–28.96 |  6.01 |
| F2    | asyncio     | sequential     |  18.54 | 18.13–19.41 |  5.10 |
| F2    | asyncio     | four in flight |  14.34 | 14.12–15.45 |  4.71 |
| F3    | asyncio     | four in flight |  11.55 | 11.47–12.29 |  2.95 |

Each added cost subtracts the caller's F0 statistic, 12.41 µs (synchronous, four in flight) or 11.36 µs (asyncio, sequential).

| Family | Synchronous added cost       | Asyncio added cost       | Eligible |
| ------ | ---------------------------- | ------------------------ | -------- |
| A      | −5.55 µs (F1 four in flight) | −4.83 µs (F1 sequential) | yes      |
| B      | 12.34 µs (F2 four in flight) | 7.17 µs (F2 sequential)  | yes      |

A local hit cost less CPU than a `CacheCore` hit in every cell. B qualifies by 0.46 µs for the synchronous caller, whose four-thread cell costs 10.51 µs more per hit than its sequential cell. Its asyncio caller qualifies without F3, because F2 at four in flight adds only 2.98 µs, so B would not include batching.

**Choice.** A is eligible, so A is built. B is built only if A stops for a failed safety scenario or the memory criterion.

Reproduce at that revision from the repository root with `PYTHONPATH=. uv run --with ./native/shared-index -- python research/shared_index_floors/floors.py --output benchmark-reports/shared-worker-cache/v5-floors.json`; the raw report stays untracked.

## Paths and equivalent work

- `direct` and `independent` are version 4's baselines.
- `shared-index` is candidate A. Version 4's research owner process holds one `CacheCore`, one change stream per active database and the 96 MiB group budget. Its core keeps each admitted payload only in a shared arena and publishes every resident `_id` identity entry into a sealed, read-only shared index. Each worker opens one control connection, which carries the index and the worker's hit ring, next to version 4's RPC connections. An `_id` `find_one` is served from the index when the five read checks pass. Otherwise it falls back to version 4's `select-identity` RPC. Misses, admissions, sorted finds and every other read keep version 4's owner RPC or native execution.

Version 4's `shared` path already stopped at screening and is not repeated. Every path performs version 4's decode and checksum work per result. Each report's environment records the extension's version, the `rustc` that compiled it, the maturin generator and wheel tag, and the SHA-256 of `native/shared-index/Cargo.lock`. Measurements on a tree with uncommitted changes under `benchmarks/`, `native/`, `src/` or `reports/` are rejected.

## Phases and inference

Version 4's phases, cells, blocks, counterbalancing, estimands, gate and futility rule apply with `shared-index` in place of `shared`. Within block `b`, paths run in the `b mod 6`-th lexicographic permutation of `(direct, independent, shared-index)`. With one built candidate, the all-must-pass conjunction uses nominal 95% intervals. The gate output names the candidate in every comparison and gives its verdict.

## Integration criterion

Version 4's "one cache algorithm/router" becomes: `CacheCore` remains the authority for admission, eviction and generations; published state serves only what the core would serve, enforced by the differential check. A local hit needs a validity check outside the core. The amended wording keeps the property behind version 4's rule, that no admission or eviction policy diverges from the core, and makes it testable.

## Deadlines and bounds

Version 4's deadlines and bounds apply unchanged, including the 3-second upstream-progress expiry, which local hits enforce from published progress. The shared index adds these:

| Bound                | Value                                                                                                | Source                                                |
| -------------------- | ---------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| Owner-exit detection | Local hits stop within 100 ms after the owner exits                                                  | `tests/shared_cache/test_scenarios.py`                |
| Local read attempts  | 4 version-checked copies, after which the read counts as absent                                      | `READ_ATTEMPTS` in `native/shared-index/src/index.rs` |
| Index slots          | 32,768, of which at most 24,576 hold published entries                                               | `shared_index.slots`                                  |
| Payload arena        | 128 MiB: the 96 MiB budget, up to one eighth for size-class rounding, block headers and key blocks   | `shared_index.arena_bytes`                            |
| Namespaces           | 1                                                                                                    | `shared_index.namespaces`                             |
| Hit ring             | 16,384 slot tokens per worker session, drained on the owner's 50 ms sweep; a full ring drops touches | `shared_index.ring_tokens`                            |

A `primary` entry occupies a 4,608-byte arena block and a `large` entry a 73,728-byte block, so each hot set fits with room for key blocks. A window fails setup unless the owner has published every primed `_id` entry, so a capacity shortfall cannot silently turn local hits into RPC hits.

## Fault cases

The `fault` phase runs version 4's eleven cases and four more, listed under `fault_cases`:

| Case                            | Scenario test in `tests/shared_cache/test_scenarios.py`           |
| ------------------------------- | ----------------------------------------------------------------- |
| `owner-kill-during-local-hits`  | `test_a_killed_owner_stops_local_hits_within_the_detection_bound` |
| `owner-pause-during-local-hits` | `test_a_silent_owner_stops_local_hits_by_the_progress_expiry`     |
| `torn-read-stress`              | `test_concurrent_readers_never_observe_torn_payloads`             |
| `reattachment-after-restart`    | `test_a_replacement_owner_serves_only_its_own_index`              |

## Prototype safety scenarios

The deterministic scenarios run against real owner and worker processes and a disposable replica set. They cover version 4's cases and the [delta specification](../../../openspec/changes/reduce-shared-cache-overhead/specs/shared-cache-benchmarking/spec.md)'s requirements for local hits: processed invalidations, torn and reclaimed reads, stable owner snapshots, owner-loss fencing, bounded reclamation, read-only published state and liveness detection without competing readers. A Hypothesis state machine checks published state against the authoritative core. `loom` models check the version protocol and reclamation. Run them before collecting decision evidence:

```console
cargo test --manifest-path native/shared-index/Cargo.toml
RUSTFLAGS="--cfg loom" cargo test --release --manifest-path native/shared-index/Cargo.toml
just pytest -- tests/shared_cache tests/benchmark/stream_cost/test_shared_cache_run.py tests/benchmark/stream_cost/test_shared_cache_run_integration.py
```

## Calibration result

Version 5's baseline-only calibration followed version 4's rule at revision `59c5dbd09c04cb272c4e2f66f83eb5225a6d1481` from the pending configuration with SHA-256 `318ba02bee6625ef6507869a0ac66e5eb6c5e9d8d3532a488b24a74328b57da5`. All 294 windows were healthy: 114 closed-loop probes and 180 open-loop validations. Throughput is reads/s, and the ranges are the three probe windows of the weakest cell in each family.

| Family      | Weakest probe cell                  | Probe throughput | Rate attempts                                                                                        | Frozen rate | Frozen window         |
| ----------- | ----------------------------------- | ---------------: | ---------------------------------------------------------------------------------------------------- | ----------: | --------------------- |
| Primary     | direct, synchronous, one worker     |      2,604–2,706 | 1,953 failed: the one-worker synchronous direct cells completed 95.8–97.0% in the window; 976 passed |         976 | hot 30 s, active 60 s |
| Cold miss   | independent, asyncio, 4 workers     |      8,946–9,216 | 976 (primary rate) passed                                                                            |         976 | 10.2 s                |
| Sensitivity | direct `find16`, asyncio, 8 workers |          426–451 | 319 passed                                                                                           |         319 | 32 s                  |

In primary-family probes, independent managers sustained 34,100–164,400 reads/s and direct reads 2,600–22,900 reads/s, so every frozen rate leaves both baselines well below saturation at four and eight workers. Validation windows issued every write within 3 ms of schedule; the slowest write took 0.44 s.

The test host's one-worker direct probes ran slower than version 4's 3,380–3,626 reads/s, so the primary rate fell from version 4's 1,267 to 976 reads/s. Versions are therefore compared only within this registration. The calibration ran in three consecutive invocations, because the agent's task runner stops a command after two hours: the second and third resumed the earlier report with `--resume` at the same revision and registration, copying the completed windows and running the rest fresh. The frozen values come from the third report.

## Reproduction

From the repository root, after the [contributor setup](../../../CONTRIBUTING.md), which builds the extension from the committed sources and lockfiles:

```console
source scripts/testcontainers-bridge.sh
uv run -- python -m benchmarks.stream_cost.shared_cache.run --smoke --config reports/shared-worker-cache/v5/config.json --output benchmark-reports/shared-worker-cache/v5-smoke.json
uv run -- python -m benchmarks.stream_cost.shared_cache.run --calibrate-baselines --config reports/shared-worker-cache/v5/config.json --output benchmark-reports/shared-worker-cache/v5-calibration.json
uv run -- python -m benchmarks.stream_cost.shared_cache.run --config reports/shared-worker-cache/v5/config.json --freeze benchmark-reports/shared-worker-cache/v5-calibration.json
uv run -- python -m benchmarks.stream_cost.shared_cache.run --phase screening --config reports/shared-worker-cache/v5/config.json --output benchmark-reports/shared-worker-cache/v5-screening.json
uv run -- python -m benchmarks.stream_cost.shared_cache.analysis benchmark-reports/shared-worker-cache/v5-screening.json --config reports/shared-worker-cache/v5/config.json --phase screening --blocks 6
```

Later phases use the same two commands with their phase name and registered block count. Use a new output path for every run; raw reports stay untracked. A run interrupted by the host can continue with `--resume <earlier report>` at the same revision and registration.
