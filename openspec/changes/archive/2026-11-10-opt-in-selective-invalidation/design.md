# Design

## Context

See `proposal.md` — Why. The production constructor imports at `acc1de2f` and `55807be3` select `_shared_index.LocalCacheCore` in both execution models. The required integration points are:

- `native/shared-index/src/local_cache.rs`: `State`, `Namespace`, `Body::Namespace`, find families, stable tokens, admission planning, LRU, and capture ownership under `Arc<Mutex<State>>`.
- `local_cache/shared.rs`: the related shared-owner implementation, which receives no selective policy in this change.
- `_core/native.py`, `contracts.pyi`, and `_shared_index.pyi`: Python/native configuration, codec, outcome, and typing boundaries.
- `_core/stream_events.py`, both coordinators/supervisors, and the collection/cursor adapters: projection, event routing, final request options, and native execution.
- `CursorCapture` owns encoded result accumulation; native `Capture` owns validity and reservations, including idempotent release, `Drop`, and Python GC support.

The separate `remove-nonproduction-library-code` change removes the obsolete Python engine and development-only bindings. Apply that cleanup before this feature or rebase this feature onto its completed source; do not implement against or preserve that engine. Historical research supplies workload evidence, not a runtime backend.
The accompanying deltas resolve explicit conflicts with ordinary-generation admission and the routing-only projection. Existing index-change behavior is preserved, including index-generation validation of query entries.

## Goals / Non-Goals

**Goals:** The four deltas are the behavioral authority. The implementation should keep policy evaluation in the common core and leave the adapters responsible for native execution and effective options.

**Non-Goals:** No second read implementation, generic query evaluator, shared-worker protocol change, dependency analysis for document-returning updates, or repeat of the completed exploratory research. The configuration mapping is finite caller-owned input copied once; runtime namespace tracking must not expand it.

## Decisions

The alternatives below require no additional research or follow-up beyond their named implementation verification tasks. Decisions without such tasks have no unresolved implementation questions.

### D1. Normalize policy once at construction

Put the frozen public configuration and normalization in a common module, with exports from the package root and both execution-model packages. Keep this configuration separate from `CacheCoreConfig`: it describes MongoDB namespaces and stream payloads rather than storage capacity. Retain the issue's API spelling. Normalize once into immutable per-database maps supplied to native local-core construction and the coordinator; resolve each cached view's policy once from that snapshot. The native constructor consumes policy presence to enable guards without retaining a duplicate Python mapping; remove disabled policies from the runtime maps. Compile each affected database's pipeline once and reuse it on retry/reopen. Managers with no enabled policies follow the existing pipeline builder and do not allocate selective state.

Alternative: mutating a collection's policy at first access would be convenient for dynamic applications but would require stream reconfiguration and a new continuity protocol. A generic callback policy would be extensible but could not ensure agreement between projection and routing. Neither is warranted by this constructor contract.

### D2. Extend native guards and atomic publication

Add an explicit native guard variant for selectively protected query results in `local_cache.rs`, alongside the existing ordinary query-token and identity guards. Keep ordinary namespace generation advancement for every write. The selective variant includes the namespace's non-reused identity, epoch, index generation, fallback version, and proof-group token/version; `Capture` also retains availability and release protection. Do not introduce Python `CacheEntry`, `NamespaceState`, or storage indexes.

Exact and compatible lookup validate the resident native node's guard. Preserve unrelated selective find-family sources when a write invalidates other nodes, and use the actual source token for compatible reuse. On a miss, adapters classify the final prepared query once and obtain a native capture before executing against MongoDB. Reuse its descriptor through admission. If no group can be acquired, capture the existing ordinary query token instead. Leave query identity and canonicalization semantics unchanged.

Native `State` remains the authority for capacity, guard checks, replacement, index publication, and reclamation. Extend the existing admission planning/commit path; do not reproduce Python's former split physical-insertion and post-publication workflow. Keep the existing versioned pin/revalidation protocol for Python equality or other callbacks outside the mutex. Validate group and namespace ownership before committing a replacement so an older capture cannot displace a newer node. Identity invalidation still runs even when all selective queries survive an event. An advanced `record_write` call without a classified hint uses conservative invalidation.

Alternative: a separate Python selective cache duplicates ownership and adds boundary crossings, while overloading the ordinary query token conceals writes from other readers. Extending the current native guard representation fits the existing owner. Reuse of the pin and commit protocol is verified in task 2.2; runtime costs are measured in task 4.2.

### D3. Bound proof groups within the existing native owner

Allocate the selective registry lazily in native `State` for enabled local policies, with one manager-wide capacity of initially 1,024 groups, including groups held only by captures. A group is identified by its non-reused namespace identity, optional canonical partition, and optional count-dependency signature. Bound signatures to 32 paths of at most 64 UTF-8 bytes each and partition strings to 64 UTF-8 bytes. Native rows and captures share group tokens with resident/capture reference counts. Unconfigured owners allocate no groups; the shared owner accepts no selective configuration.

The existing state mutex serializes reservation, reference publication/release, pruning, and the capacity decision regardless of `max_entries`. No additional capacity, namespace, or LRU mutex hierarchy is introduced. Canonicalization, Python equality, codecs, logging, I/O, awaits, and Python-reference destruction must remain outside that mutex, following the current pin/revalidation and `Retired` patterns. Build bounded descriptors before locking; revalidate namespace and owner state when committing them.

Index groups by partition for known inserts, with a separate collection of groups lacking an insert proof. Update routing examines bounded dependency groups and invalidates groups lacking an update proof. Unknown hints, replacements, and deletions advance a common fallback version. Advance the ordinary query token independently. Writes to unseen partitions allocate no groups. At capacity, use ordinary capture/admission without evicting a live group. Release a group only when no row or capture needs it, and use non-reused tokens to prevent revival after slot reuse.

Extend `Capture::release_reservation`, its `AtomicBool` idempotence, `Drop`, and `__clear__` to release selective reservations under the same native ownership protocol as identity captures. Explicit count completion/error handling and cursor finish/abandon/oversize/encoding failure/close/cancellation release early. An unreachable partially consumed cursor drops its native capture even when close was omitted. Native storage must not strongly own the Python capture; preserve GC traversal and release retired Python references after unlocking so cycles and reentrant finalizers remain safe. Do not add a second Python weak-lease registry or a Python destructor that acquires native locks.

Eviction, displacement, failed admission, clear, drop, and close update exact native references. Stale cleanup cannot release a replacement's reservation. Dropped namespaces can leave invalid owners held by active captures; those still consume the global bound until release, so repeated recreation cannot bypass capacity accounting. Capture release remains safe after core close. Verify the bound through production cache behavior, existing snapshots, weak references, and memory measurements; do not add test-only ownership bindings.

Alternative: historical value counters grow without bound; fixed hash buckets add collision invalidations; a second lease mechanism duplicates capture lifecycle machinery. Bounded exact native groups reuse the existing owner and provide the selected retention behavior. Capacity, GC, reentrancy, and slot reuse are covered by tasks 2.2–2.3. The working-set and memory costs of the initial cap are measured in task 4.2.

### D4. Prove a useful subset without executing MongoDB predicates

Implement partition and count-dependency extraction as separate common classifiers. They consume immutable snapshots of the final filter and effective read options; they never rewrite the native filter. Preserve the existing bypass precedence. Run classification only when enabled and after an ordinary exact/compatible miss; cache-resident proof descriptors supply warm-hit validity.

Partition extraction initially recognizes a direct field scalar or a sole `$eq` predicate, including explicit `$and` conjunctions. Other conjuncts may be arbitrary already-cacheable predicates if the required equality remains certain; conflicting or unsupported uses of the partition field fail the proof. Do not infer partitions through `$or`, `$expr`, `$in`, array equality, or null. Require confirmed simple effective collation. Reuse the identity numeric-equality canonicalization seam (`canonical_order_sensitive_key`), not discriminator subtype tags or Python's untagged Boolean equality. Accept BSON int32/int64, Boolean, bounded strings, and `ObjectId` for query proofs. Double/decimal query proofs can remain ordinary; double/decimal insert values return unknown initially, preventing cross-type equality mistakes without a numeric projection evaluator.

Count extraction accepts empty filters, plain field equality (including null), `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte`, `$in` and its negative membership counterpart, `$exists`, and recursively supported `$and`, `$or`, `$nor`. Collect every referenced field, independent of operand values; reject unrecognized operators, expression references, malformed paths, and signatures exceeding D3. Dotted non-numeric query paths are supported; record whole array fields conservatively, without reasoning about array positions. Compare update and dependency paths by exact equality or a dot-delimited prefix in either direction. Numeric path components or ambiguous event names force unknown. Explicit count hints disable update-dependency proofs, while preserving independently valid insert-partition proofs under all existing scalar and effective-collation restrictions. Every update invalidates a hinted count because index membership can depend on fields absent from the query, as illustrated by MongoDB's [hinted sparse count](https://www.mongodb.com/docs/manual/core/index-sparse/#sparse-index-and-incomplete-results). Existing option validation and native execution remain authoritative.

Alternative: deriving arbitrary dependencies from expressions or using Python equality would cover more shapes but require a MongoDB semantic evaluator. Returning ordinary proofs for uncertain shapes preserves useful caching without that risk. Real-server BSON and path qualification is required in task 3.1.

### D5. Compile collection-conditional bounded hints

Extend the common pipeline builder with a per-database policy map. Gate expressions on collection name and operation type using `$switch`/`$cond`, with `$$REMOVE` for unconfigured events. Preserve telemetry's current conditional timing fields. Use one literal field lookup for the configured top-level insert value and an explicit known/unknown envelope. Extend the experimental scalar projection with `ObjectId` support; only D4's supported wire types pass the value bound.

For updates, adapt the experimental name projection using MongoDB's [update-description contract](https://www.mongodb.com/docs/manual/reference/change-events/update/): concatenate updated keys, removed fields, and truncated-array paths; emit at most 32 names, each at most 64 UTF-8 bytes. Validate required update-description components instead of treating absent descriptions as an empty change. Treat nonempty path disambiguation metadata or numeric/ambiguous paths as unknown; do not transmit updated values. Arrays changed as a whole, at a position, or by truncation must all reach a conservative routing decision. Unknown hint shape, missing hint on an expected operation, or overflow takes the fallback fence.

Alternative: separate streams could avoid conditional expressions but add cursors and recovery owners. Full-document payloads simplify local analysis but scale with values and violate the selected cost model. Conditional projection is the existing database-stream architecture's natural extension. MongoDB expression boundary behavior needs real-server verification in task 3.1.

### D6. Reuse measurements while replacing experimental execution

Add a production mode to the existing end-to-end workload infrastructure. Instantiate normal public managers and policies; remove `GuardRouter`, fake namespace generations, and read-method replacement from this mode. The current tree retains no experimental cache backend; historical experiments are reproduced only at their recorded Git revisions. Reuse deterministic writes, independent result oracles, command counts, CPU/container sampling, and byte proxies. Measurement instrumentation may observe routing but must not replace its decisions. Compare full production traffic through the normal manager client; report stream logical bytes separately from total TCP if shared sockets prevent reliable stream-only TCP attribution.

Run matched release builds of `main` and the implementation on the same pinned MongoDB topology, interpreter, workload, and host conditions. Compare existing test duration separately from new tests. Use four counterbalanced blocks; begin with selected cells below, inspect noise only after completing a block, and extend only unresolved comparisons. Do not repeat the historical full transport matrix.

| Comparison                                         | Focused workload                                                                                                                                                   | Evidence to retain                                                                                                                      |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| Main versus unconfigured production                | Warm exact/prefix/count/identity hits, admission and invalidation; mixed-policy database's ordinary sibling                                                        | Per-read CPU/latency, routing CPU, projected payload, native command counts                                                             |
| Each option versus its disabled production control | Matching insert or update churn; 200 B, 2 KB and 20 KB documents; 10 and 100 reads/write; 4,096 reads/cell                                                         | Read savings comparable to the report's matching workload, client/server CPU, P50/P99, elapsed time, total TCP and logical stream bytes |
| Both options versus disabled control               | Same author feed/count workload with alternating inserts and updates, including matching and irrelevant writes                                                     | Both proofs operate in the same production run; no wrong post-event results                                                             |
| Enabled nonmatching and unrelated controls         | Opposite write mix, writes to an unconfigured sibling, reads of an ordinary sibling during configured writes; 10 and 100 writes/second                             | Projection/routing overhead separated from read savings, including unavoidable configured-stream contention                             |
| Bounded state                                      | More than D3's capacity across concurrent namespaces and queried partitions, write-only values, capture abandonment, eviction, drop/recreate with delayed captures | Capacity fallback/reuse through cache behavior, collectability of detached captures, retained bytes and RSS trend; no historical growth |

Accept a net-benefit claim only with repeatable saved reads and reduced total work in matching workloads, reporting client and server costs separately. Do not transfer historical percentages directly to production or use mixed-direction noise as proof of no regression. Investigate every reproducible slowdown; fix it or obtain the maintainer's explicit approval for its measured trade-off before completion. Unconfigured collections must do no selective query analysis or payload processing; conditional server dispatch in a database with active policies must be measured rather than described as free.

Record a concise production summary, versions, commands, controls, and measured bottleneck in `docs/development/selective-invalidation.md`; raw data stays untracked under `/tmp/agents/`. Do not rewrite historical observations. Unknown net benefit, server expression cost, and working-set overhead are resolved by task 4.2.

### D7. Keep guidance canonical

Put configuration signatures and eligibility limits in `docs/user/reference/api.md`, practical opt-in examples and cost selection in a new `docs/user/usage/selective-invalidation.md`, and link the existing consistency guide for freshness semantics. Replace the unconditional refresh claim in `docs/user/usage/cached-reads.md` with links to the applicable policies. Link supporting details from the README only where needed and update existing Context7 rules by meaning instead of accumulating overlapping rules. Keep D3's internal capacity rationale and D6's evidence in maintainer documentation.

Alternative: repeating the full contract in each guide is convenient locally but creates contradictory maintenance paths. Links preserve one source for each concern.

## Risks / Trade-offs

- Extra projected names require server-side inspection of the update description before the output can be bounded → D6 measures server CPU and large updates; bounded payload is not a bound on server work.
- Longer-lived results can expose the existing asynchronous event window more often → the public explanation is owned by the selective guidance requirement, without implying stream health proves catch-up.
- Update routing can scan many proof groups within the manager-wide cap → D3 limits the scan and D6 measures high-cardinality controls; a reverse dependency index is justified only by those results, since it adds another ownership structure.
- Guard references cross Python cursors and native capture lifecycles → deterministic admission fault injection and operation-ordering tests cover all release paths before performance evidence is accepted.

## Migration Plan

This adds opt-in constructor data without a persisted format or data migration. Removing the configuration on the next manager construction restores ordinary operation. Existing managers cannot be reconfigured in place. Release guidance must describe current behavior only. Planning ends with these artifacts; implementation begins only through the apply workflow.
