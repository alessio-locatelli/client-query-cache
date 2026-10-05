# Design

## Context

See [proposal.md](proposal.md) for motivation. Native sync and async cursor subclasses already defer `_prepare()` until execution, read the final PyMongo cursor fields, and construct an order-sensitive discriminator containing `find`, filter, projection, ordered sort, skip, limit, collation, and codec fingerprint. An eligible miss uses `CursorCapture` to admit only complete immutable BSON snapshots. A hit decodes into a private buffer.

`CacheCore.lookup_namespace()` currently records an exact-key miss immediately. `NamespaceState.entry_index` owns reclamation tokens, and `_finalize_put()` publishes tokens only after conditional insertion and generation validation, then checks eviction before publication. LRU and namespace locks are deliberately acquired in separate sections. These ownership and locking boundaries must also govern the compatibility index.

The existing cache-core scenario says that any differing query input prevents reuse. The delta distinguishes physical keys from supported subsumption. No main spec or runtime code is changed during this proposal.

## Goals / Non-Goals

**Goals:** Add source discovery in the shared core, carry structured find metadata through existing admission, and keep the two cursor integrations thin. Compatibility must never extend admission eligibility or weaken the existing validity decision.

**Non-Goals:** A general cache predicate engine, payload copies for every limit, stronger ordering guarantees, or a new serialization format. The declared source limit determines coverage; exhaustion of a smaller-limit query does not promote it to an unlimited source.

## Decisions

### 1. Build an exact identity and a limit-independent family from one final shape

Add a small shared find-shape helper under `_core`, consumed by both `_prepare()` methods. Its exact discriminator includes the final limit. Its family includes everything except that limit; the owning `NamespaceState` supplies namespace scoping. Store a typed family/limit descriptor with eligible complete source admissions, not a parser that infers find options from generic canonical tuples. Integer zero denotes unlimited; booleans and negative limits never register as compatible sources or request compatibility.

Derive exact identity and family from the same final query shape, preserving the filter representation already used by find execution. This change does not add or require a normalization helper.

Both plans use identical operation-neutral wording for the shared cache-core requirement and separate added requirements for each feature. Either change can be implemented and synchronized independently.

| Alternative                                        | Benefits                                                                               | Costs and conclusion                                                                                                                               |
| -------------------------------------------------- | -------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- |
| Shared structured shape and descriptor, chosen     | One definition of compatibility; no decoding of canonical keys; matches final chaining | Adds a small internal value type. Codec and limit-type distinctions are covered in tasks 2.1 and 3.2; no separate research is needed.              |
| Extract a family from generic discriminator tuples | Avoids admission metadata                                                              | Couples the core to representation tags and cursor tuple positions; fragile under normalization. No prototype or follow-up is needed to reject it. |
| Build separate shapes in each cursor module        | Minimal shared-core additions                                                          | Duplicates correctness-sensitive logic across APIs. No research is needed to reject it.                                                            |

### 2. Maintain one namespace-local family index of resident source tokens

Use a dictionary from family identity to source tokens, keyed by the actual entry token. Each token records its physical key and declared limit; payload bytes remain solely in the LRU entry. Include optional find-source metadata in admission/entry ownership so `_discard_entry_locked()` can remove the exact token directly, including after replacement. Delete empty family buckets.

Publish compatibility metadata in the same namespace decision as `entry_index`, through `_finalize_put()`'s admission hook. Reuse the existing post-publication residency check. Cleanup for displacement, eviction, rejected publication, namespace clear/create, and close must follow exact entry identity. Old cleanup must not remove newer tokens. Ordinary writes can clear the namespace's family buckets when they advance the generation, preventing stale-source candidate buildup; entry cleanup must tolerate a bucket already cleared by invalidation.

For a family containing `k` resident limits, snapshot its tokens under the namespace lock, release that lock, and inspect only that snapshot. Prefer a valid exact source, then the smallest valid covering positive limit, then unlimited. Scan all relevant tokens if needed to skip stale or evicted candidates; a stale best candidate must not hide another valid source. Source selection is internal and promises only a prefix of a valid cached result, not a new stable order for unsorted queries or tied sorts.

| Alternative                                 | Benefits                                                                                | Costs, unknowns, and conclusion                                                                                                                                                  |
| ------------------------------------------- | --------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Family dictionary with a local scan, chosen | Simple ownership and removal; lookup independent of unrelated cache size; no dependency | Lookup is O(k). Representative many-limit cost is unknown and measured in tasks 1.1 and 4.1. This satisfies the required family bound without speculative indexing.              |
| Ordered limits with binary search           | Faster successor discovery for very large families                                      | Adds insertion/removal complexity and still needs validity handling. Its practical benefit is unknown; task 4.1 compares observed family scaling before any such adjustment.     |
| One largest-result pointer per family       | Constant candidate selection                                                            | Eviction can hide smaller covering resident results unless another index restores them. Reject because it complicates required source discovery; no separate research is needed. |
| Scan all LRU or namespace entries           | No family metadata                                                                      | Cost grows with unrelated queries and violates the lookup bound. No research is needed to reject it.                                                                             |
| Admit every requested prefix                | Reuses existing exact lookup                                                            | Duplicates bytes and changes storage with demand for smaller limits. Violates the storage requirement; no research is needed.                                                    |

### 3. Make exact and compatible discovery one core lookup operation

Add a find-specific lookup operation while preserving `lookup_namespace()` for other reads. Check availability first, then probe the exact key without recording statistics. On exact failure, eligible positive-limit requests consult the family index. For each candidate, check that its token still identifies the resident source and compare the actual entry generation under the existing namespace validity boundary. Do not nest LRU and namespace locks.

On success, touch the source's physical key and record one hit; record one miss only after all permitted discovery fails. Keep the existing bypass semantics when availability is lost. The hit's validity decision and subsequent decode form the same snapshot boundary as existing exact lookup; this does not add a synchronous change-stream barrier or prevent an invalidation after that decision.

Calling `lookup_namespace()` and compensating its miss counter afterward would expose inconsistent observations and couple APIs to telemetry internals. An unrecorded probe shared internally by lookup paths is acceptable if it reduces duplication; no public counter-repair API is needed. Tasks 2.3 and 3.3 settle factoring and verify candidate/availability races; no independent research is needed.

### 4. Reuse BSON decoding and load only the requested prefix into the cursor

Decode the selected resident source using the requesting codec profile, then take at most the requested limit before installing the existing local cursor buffer. This preserves mutation isolation through the existing serialization boundary. Set `retrieved` to the number loaded, retain the native local cursor metadata, and leave the admission capture absent on a hit. Partial prefix consumption therefore cannot duplicate a resident source. Clone, rewind, synchronous indexing, and slicing recompute final query shape through the existing native hooks.

The current BSON envelope decodes a whole stored list. The first implementation therefore spends O(source bytes) CPU and transient decoded memory even for a short prefix. This is a known cost, not a claim of prefix-only decoding. Source selection prefers smaller covering limits to reduce it. Custom partial BSON decoding could reduce allocations but introduces a serialization/codec seam and requires evidence; tasks 1.1 and 4.1 measure short-prefix hits near the entry-size limit before deciding whether additional work inside this change is justified. No custom serializer is planned without that evidence.

### 5. Verify source ownership and measure hot-path costs

Reuse the sync/async `cursors` fixture and its collection-scoped `ReadCommands` listener. Warm complete sources, clear monitored commands, then assert result prefixes and zero find/getMore commands. Capture counter and resident-entry deltas. Use `_id` ordering for exact comparisons and fixture-owned cleanup. Direct cache-core tests cover LRU ordering and family ownership without depending on timing.

Extend operation-ordering/property coverage over admission, replacement, eviction, writes, clear, availability loss/recovery, and lookup. Deterministically pause the existing publication/lookup boundaries for races. A targeted faulty guard or omitted index cleanup must cause a behavioral regression case to fail; do not test only the shape of the implementation.

Benchmark cold reads, exact hits, compatible hits, incompatible misses, and bypasses using `just pytest -n 0` and the existing cursor benchmark conventions. Vary source/request sizes, same-family limits, and unrelated families/namespaces. Record latency, command counts, transient allocation, resident bytes, and index size; unrelated entries must not expand candidate inspection. Tasks 1.1 and 4.1 own baselines and post-change measurement. Numeric latency limits are unknown until measured; no speedup percentage is promised.

| Path                 | Expected local cost                                           | Remote work                           |
| -------------------- | ------------------------------------------------------------- | ------------------------------------- |
| Shape construction   | O(query representation size)                                  | None                                  |
| Exact probe          | Expected O(1), plus validity and decode                       | None on hit                           |
| Compatible discovery | O(k) tokens and transient snapshot references in one family   | None on hit                           |
| Compatible decode    | O(source bytes), prefix buffer O(requested documents)         | None                                  |
| Miss                 | Existing streaming/capture cost; O(1) index token publication | Native find and caller-driven getMore |
| Source cleanup       | Expected O(1) token removal per reclaimed entry               | None                                  |

## Risks / Trade-offs

- [A stale metadata token reaches a fresh physical key] → Compare source token identity and generation, and remove tokens by exact ownership.
- [Publication races eviction or clear] → Use existing finalization and post-publication checks; tasks 3.3 and 3.4 exercise these orderings.
- [Large families or payloads dominate lookup cost] → Measure both dimensions separately in task 4.1; preserve the family bound and avoid unmeasured serializers.
- [Negative single-batch semantics or boolean/int key equality leak into compatibility] → Exclude those limit types from source registration and compatible requests, retaining exact native behavior.
- [Exact and family filter representations diverge] → Derive both from the same executed shape without changing the filter component; task 2.1 verifies that boundary.

## Migration Plan

No persistent cache data exists to migrate. Implement the shared core and admission descriptor, integrate both cursor paths, and update current public guides and rules in the same change. Do not add a mode or feature flag. Reverting the implementation restores exact-only reuse; process-local cache entries are rebuilt when managers restart. Archive only after implementation, measurements, and review are complete.
