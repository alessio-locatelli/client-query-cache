# Design

## Context

See `proposal.md` — Why. Inspection at `acc1de2f` found these integration points:

- `_core/stream_events.py` builds one common routing projection; sync/async supervisors build it on stream open and reopen.
- `_core/manager.py::record_write` advances the ordinary namespace generation, clears find-family metadata, and advances the affected identity's generation. Namespace lookup compares `query_generation_key`; admission performs pre-publication and post-insertion checks.
- `NamespaceState` owns reclamation indexes and find families. Identity state already demonstrates resident/capture references and safe pruning.
- Counts use namespace lookup/capture directly in each collection adapter. Finds prepare their final shape in each cursor's `_prepare`, then share `CursorCapture`. Collection eligibility already obtains the collection's default collation.
- The research runner uses `GuardRouter`, fixed queries, and patched runtime seams. Its workload, oracle, byte proxy, and CPU measurements are reusable; its guards are not the production implementation.

The accompanying deltas resolve explicit conflicts with ordinary-generation admission and the routing-only projection. Existing index-change behavior is preserved, including index-generation validation of query entries.

## Goals / Non-Goals

**Goals:** The four deltas are the behavioral authority. The implementation should keep policy evaluation in the common core and leave the adapters responsible for native execution and effective options.

**Non-Goals:** No second read implementation, generic query evaluator, shared-worker protocol change, dependency analysis for document-returning updates, or repeat of the completed exploratory research. The configuration mapping is finite caller-owned input copied once; runtime namespace tracking must not expand it.

## Decisions

The alternatives below require no additional research or follow-up beyond their named implementation verification tasks. Decisions without such tasks have no unresolved implementation questions.

### D1. Normalize policy once at construction

Put the frozen public configuration and normalization in a common module, with exports from the package root and both execution-model packages. Keep this configuration separate from `CacheCoreConfig`: it describes MongoDB namespaces and stream payloads rather than storage capacity. Retain the issue's API spelling. Normalize once into immutable per-database maps shared by core and coordinator; remove disabled policies from the runtime maps. Compile each affected database's pipeline once and reuse it on retry/reopen. Managers with no enabled policies follow the existing pipeline builder and do not allocate selective state.

Alternative: mutating a collection's policy at first access would be convenient for dynamic applications but would require stream reconfiguration and a new continuity protocol. A generic callback policy would be extensible but could not ensure agreement between projection and routing. Neither is warranted by this constructor contract.

### D2. Store reusable proof descriptors alongside guarded entries

Keep the ordinary namespace generation for all writes and existing advanced core calls. Add an explicit selective guard variant to the shared capture, entry, and lookup contracts rather than overriding `NamespaceState.generation` as the experiment did. A selective guard carries the namespace epoch, index generation, availability capture, an owner identity, a conservative-fallback version, and its local write version. Identity reads continue through their existing path; event routing must perform identity invalidation even if every selective query survives.

Exact lookup validates the guard on the resident entry without reparsing its filter. Compatible find lookup validates the actual source's guard; preserve unrelated selective find-family members instead of unconditionally clearing the entire family index. On a miss, classify the already prepared final query once, acquire its guard before native execution, and reuse the descriptor through admission. A candidate that cannot obtain a selective owner captures the ordinary namespace generation instead. Physical query identity and existing key normalization do not change.

Keep post-insertion validation and exact-token rollback in the same core admission machinery. Do not compare unlike guard versions lexicographically: stale replacement decisions validate owner/epoch and applicable versions before ordering competing admissions. A shared predicate handles exact, compatible, pre-admission, and post-insertion validity.

Alternative: maintaining a separate selective result cache could isolate changes to old entries but would duplicate admission, byte/count limits, eviction, and cursor behavior. Overloading the ordinary generation would be smaller but would invalidate all selected results or conceal writes from other consumers. Explicit guards add representation work while preserving the existing ownership boundary. Concurrency and runtime costs require verification in tasks 2.2 and 4.2.

### D3. Bound owners and release them with their consumers

Use lazy namespace registries backed by one manager-wide capacity of initially 1,024 proof groups, including groups held only by captures. A group is identified by its namespace, optional canonical partition, and optional count-dependency signature; ordinary reads consume no group. Bound dependency signatures to 32 distinct paths of at most 64 UTF-8 bytes each; partition strings to 64 UTF-8 bytes. Share group descriptors among resident entries and captures. Refuse a new group at capacity and use ordinary capture/admission without evicting a still-referenced group. The metadata bound is separate from the BSON value budget and remains active when the record-count limit is disabled.

Allocate a dedicated selective-capacity lock whenever a manager has enabled policies. It serializes group reservation, reference publication/release, pruning, and manager-wide capacity accounting regardless of `max_entries`. The existing retention section is a `nullcontext` when `max_entries=None` and cannot supply this guarantee. When locks overlap, acquire availability/retention before selective capacity, then either namespace or LRU storage; retain the prohibition on holding namespace and LRU locks together. Never acquire selective capacity from inside a storage lock or enter availability/retention while holding selective capacity. Adapt existing discard/publication callbacks to enter the selective transaction before storage locking or stage their release until storage locks are dropped. Resolve namespace registration before this transaction; perform no I/O, await, logging, or user callbacks within it. Ordinary warm-hit validation needs only its existing storage boundary, without manager-wide capacity locking.

Maintain a partition-to-groups index and a set of dependency groups. A known insert visits only groups for its partition and groups without an insert proof. A known update visits dependency groups and invalidates groups lacking an update proof. A common fallback version invalidates all groups for unknown writes, replacements, and deletions in constant time. Always advance the ordinary namespace generation separately. Event handling allocates no owner for a partition with no reads. Group versions never get reset while an owner remains reachable.

Add explicit capture release to count completion/error handling and to cursor finish, abandon, oversize, encode failure, close, cancellation, clone/rewind replacement, and preparation failures. Connect resident-reference release to the existing entry discard and eviction callbacks. Failed or rolled-back publication releases its own reference; stale callbacks must not release a replacement's reference. A released registry slot receives a fresh owner identity, so old captures cannot become current after reuse. Namespace clear/drop and manager close detach the registry and invalidate outstanding owners. Detached owners held by active captures continue to consume manager-wide capacity until their last reference releases; repeated namespace recreation must not circumvent the bound.

Represent each active capture's ownership with a lease held strongly only by that capture, and track it through callback-free weak references in its proof group. The registry must not retain the capture or cursor through another strong path. Explicit release removes the lease idempotently. If a cursor is discarded without closing, collection of its capture expires the lease without running cache cleanup in a destructor or weak-reference callback. Prune expired leases for a group when acquiring or releasing its references; before declining a new group at capacity, sweep the bounded registry, including detached groups, and reclaim groups with neither live leases nor resident references. Do not retain expired lease records across repeated acquisitions. Collection followed by the next capacity acquisition therefore makes abandoned owners reusable without adding locks, waits, or asynchronous work to finalization.

Alternative: historical per-value counters give simple lookup but grow with writes. Hash buckets offer a fixed small array and no capture references, but collisions unpredictably invalidate unrelated partitions. An exact bounded registry reuses the existing identity-state ownership model and preserves targeted savings until capacity. Destructor-based decrementing would make reclamation immediate but can re-enter non-reentrant storage locks or require unavailable async cleanup; weak leases move cleanup into normal ordered transactions. Deadlock and collection behavior are verified in tasks 2.2 and 2.3. The initial cap's working-set effect and retained overhead are unknown until task 4.2; changing that internal bound does not change public eligibility.

### D4. Prove a useful subset without executing MongoDB predicates

Implement partition and count-dependency extraction as separate common classifiers. They consume immutable snapshots of the final filter and effective read options; they never rewrite the native filter. Preserve the existing bypass precedence. Run classification only when enabled and after an ordinary exact/compatible miss; cache-resident proof descriptors supply warm-hit validity.

Partition extraction initially recognizes a direct field scalar or a sole `$eq` predicate, including explicit `$and` conjunctions. Other conjuncts may be arbitrary already-cacheable predicates if the required equality remains certain; conflicting or unsupported uses of the partition field fail the proof. Do not infer partitions through `$or`, `$expr`, `$in`, array equality, or null. Require confirmed simple effective collation. Reuse the identity numeric-equality canonicalization seam (`canonical_order_sensitive_key`), not discriminator subtype tags or Python's untagged Boolean equality. Accept BSON int32/int64, Boolean, bounded strings, and `ObjectId` for query proofs. Double/decimal query proofs can remain ordinary; double/decimal insert values return unknown initially, preventing cross-type equality mistakes without a numeric projection evaluator.

Count extraction accepts empty filters, plain field equality (including null), `$eq`, `$ne`, `$gt`, `$gte`, `$lt`, `$lte`, `$in` and its negative membership counterpart, `$exists`, and recursively supported `$and`, `$or`, `$nor`. Collect every referenced field, independent of operand values; reject unrecognized operators, expression references, malformed paths, and signatures exceeding D3. Dotted non-numeric query paths are supported; record whole array fields conservatively, without reasoning about array positions. Compare update and dependency paths by exact equality or a dot-delimited prefix in either direction. Numeric path components or ambiguous event names force unknown. Explicit count hints use ordinary guards: index membership can depend on fields absent from the query, as illustrated by MongoDB's [hinted sparse count](https://www.mongodb.com/docs/manual/core/index-sparse/#sparse-index-and-incomplete-results). Existing option validation and native execution remain authoritative.

Alternative: deriving arbitrary dependencies from expressions or using Python equality would cover more shapes but require a MongoDB semantic evaluator. Returning ordinary proofs for uncertain shapes preserves useful caching without that risk. Real-server BSON and path qualification is required in task 3.1.

### D5. Compile collection-conditional bounded hints

Extend the common pipeline builder with a per-database policy map. Gate expressions on collection name and operation type using `$switch`/`$cond`, with `$$REMOVE` for unconfigured events. Preserve telemetry's current conditional timing fields. Use one literal field lookup for the configured top-level insert value and an explicit known/unknown envelope. Extend the experimental scalar projection with `ObjectId` support; only D4's supported wire types pass the value bound.

For updates, adapt the experimental name projection using MongoDB's [update-description contract](https://www.mongodb.com/docs/manual/reference/change-events/update/): concatenate updated keys, removed fields, and truncated-array paths; emit at most 32 names, each at most 64 UTF-8 bytes. Validate required update-description components instead of treating absent descriptions as an empty change. Treat nonempty path disambiguation metadata or numeric/ambiguous paths as unknown; do not transmit updated values. Arrays changed as a whole, at a position, or by truncation must all reach a conservative routing decision. Unknown hint shape, missing hint on an expected operation, or overflow takes the fallback fence.

Alternative: separate streams could avoid conditional expressions but add cursors and recovery owners. Full-document payloads simplify local analysis but scale with values and violate the selected cost model. Conditional projection is the existing database-stream architecture's natural extension. MongoDB expression boundary behavior needs real-server verification in task 3.1.

### D6. Reuse measurements while replacing experimental execution

Add a production mode to the existing end-to-end workload infrastructure. Instantiate normal public managers and policies; remove `GuardRouter`, fake namespace generations, and read-method replacement from this mode. Keep the experimental paths available to reproduce the historical report. Reuse deterministic writes, independent result oracles, command counts, CPU/container sampling, and byte proxies. Measurement instrumentation may observe routing but must not replace its decisions. Compare full production traffic through the normal manager client; report stream logical bytes separately from total TCP if shared sockets prevent reliable stream-only TCP attribution.

Run matched release builds of `main` and the implementation on the same pinned MongoDB topology, interpreter, workload, and host conditions. Compare existing test duration separately from new tests. Use four counterbalanced blocks; begin with selected cells below, inspect noise only after completing a block, and extend only unresolved comparisons. Do not repeat the historical full transport matrix.

| Comparison                                         | Focused workload                                                                                                                                                   | Evidence to retain                                                                                                                      |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------- |
| Main versus unconfigured production                | Warm exact/prefix/count/identity hits, admission and invalidation; mixed-policy database's ordinary sibling                                                        | Per-read CPU/latency, routing CPU, projected payload, native command counts                                                             |
| Each option versus its disabled production control | Matching insert or update churn; 200 B, 2 KB and 20 KB documents; 10 and 100 reads/write; 4,096 reads/cell                                                         | Read savings comparable to the report's matching workload, client/server CPU, P50/P99, elapsed time, total TCP and logical stream bytes |
| Both options versus disabled control               | Same author feed/count workload with alternating inserts and updates, including matching and irrelevant writes                                                     | Both proofs operate in the same production run; no wrong post-event results                                                             |
| Enabled nonmatching and unrelated controls         | Opposite write mix, writes to an unconfigured sibling, reads of an ordinary sibling during configured writes; 10 and 100 writes/second                             | Projection/routing overhead separated from read savings, including unavoidable configured-stream contention                             |
| Bounded state                                      | More than D3's capacity across concurrent namespaces and queried partitions, write-only values, capture abandonment, eviction, drop/recreate with delayed captures | Peak/settled manager-wide owner/index counts including detached owners, retained bytes and RSS trend; no historical growth              |

Accept a net-benefit claim only with repeatable saved reads and reduced total work in matching workloads, reporting client and server costs separately. Do not transfer historical percentages directly to production or use mixed-direction noise as proof of no regression. Investigate every reproducible slowdown; fix it or obtain the maintainer's explicit approval for its measured trade-off before completion. Unconfigured collections must do no selective query analysis or payload processing; conditional server dispatch in a database with active policies must be measured rather than described as free.

Record a concise production summary, versions, commands, controls, and measured bottleneck in `docs/development/selective-invalidation.md`; raw data stays untracked under `/tmp/agents/`. Do not rewrite historical observations. Unknown net benefit, server expression cost, and working-set overhead are resolved by task 4.2.

### D7. Keep guidance canonical

Put configuration signatures and eligibility limits in `docs/user/reference/api.md`, practical opt-in examples and cost selection in a new `docs/user/usage/selective-invalidation.md`, and link the existing consistency guide for freshness semantics. Replace the unconditional refresh claim in `docs/user/usage/cached-reads.md` with links to the applicable policies. Link supporting details from the README only where needed and update existing Context7 rules by meaning instead of accumulating overlapping rules. Keep D3's internal capacity rationale and D6's evidence in maintainer documentation.

Alternative: repeating the full contract in each guide is convenient locally but creates contradictory maintenance paths. Links preserve one source for each concern.

## Risks / Trade-offs

- Extra projected names require server-side inspection of the update description before the output can be bounded → D6 measures server CPU and large updates; bounded payload is not a bound on server work.
- Longer-lived results can expose the existing asynchronous event window more often → the public explanation is owned by the selective guidance requirement, without implying stream health proves catch-up.
- Update routing can scan many proof groups within the manager-wide cap → D3 limits the scan and D6 measures high-cardinality controls; a reverse dependency index is justified only by those results, since it adds another ownership structure.
- Guard references cross Python cursor and core lifecycles → deterministic admission fault injection and operation-ordering tests cover all release paths before performance evidence is accepted.

## Migration Plan

This adds opt-in constructor data without a persisted format or data migration. Removing the configuration on the next manager construction restores ordinary operation. Existing managers cannot be reconfigured in place. Release guidance must describe current behavior only. Planning ends with these artifacts; implementation begins only through the apply workflow.
