# Shared worker cache registration, version 5

Version 5 asks whether a shared worker cache that avoids the owner round trip on hits can pass the [version 4](../v4/registration.md) gate. It reuses version 4's workload, data, phases, counterbalancing, estimands, inference, bounds and gate; version 4 stays their source. The [design](../../../openspec/changes/reduce-shared-cache-overhead/design.md) records the rationale for every difference.

**Status:** draft. This file registers the candidate selection rule before any floor is measured. Paths, bounds, the configuration, the integration criterion, fault cases and reproduction commands are added before baseline calibration, and the file is frozen with its configuration.

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
- **CPU.** User plus system time from `os.times()` of the caller process and of the owner process, taken around each repetition and divided by its completed hits.

### Rule

For each floor and caller, the statistic is the larger of the sequential and four-in-flight medians of CPU per hit. A family's added cost is that statistic minus the same caller's F0 statistic.

- **Margin.** 12.8 µs, half of the smallest version 4 allowance (0.10 × 257 µs of total CPU per request). The other half covers adapter, key-encoding and accounting work that the floors omit.
- **Eligibility.** A is eligible when F1 − F0 is within the margin for both callers. B is eligible when both callers qualify: the synchronous caller with F2 − F0, and the asyncio caller with the larger of the sequential F2 − F0 and the four-in-flight min(F2, F3) − F0.
- **Order.** Build A if it is eligible. Build B only if A is ineligible, or if A stops for a reason B does not share: a failed safety scenario or the memory criterion. B includes asyncio batching only when the asyncio caller qualifies through F3 alone.
- **No eligible family.** The study ends with the floor report and builds no candidate.

### Floor results

Pending.
