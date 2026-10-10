# Design

## Context

See [proposal.md](proposal.md) for motivation and [the delta spec](specs/cached-read-api/spec.md) for the observable contract.

Both collection facades currently materialize multi-document reads in `src/client_query_cache/{synchronous,asynchronous}/collection.py`. The core stores a BSON envelope containing the result list and decodes isolated values on lookup. Namespace captures already guard admission against writes and stream-availability transitions.

The inspected driver is PyMongo 4.18.2; `pyproject.toml` accepts versions from 4.18.1. Find cursors are lazy, whereas aggregation executes its initial command before returning a command cursor. `to_list()` has a batch-draining path separate from `next()`, and server resources can be closed while local batch documents remain unread. Async find rejects indexing and has distinct await conventions for methods including `rewind()` and `add_option()`.

The [adapter evaluation](../../../../docs/development/research/read-through-collection-adapter-evaluation.md) separates cursor compatibility from preserving fresh server errors on hits. This design retains the explicit cached-read contract: a hit avoids execution; unsafe queries and operations requiring native server behavior bypass it.

## Goals / Non-Goals

**Goals:** Move execution preparation and consumption to the cursor boundary, reuse generation protection and the existing codec/LRU, bound retained candidates, and preserve driver-owned batching, sessions, retries, and cleanup.

**Non-Goals:** Add a return-mode flag, additional manager/database/collection type parameters, a custom BSON serializer, background draining, transparent writes, or a new live-server-error contract. Count-option issue #151 is outside this change. Exact concrete type equality and private driver attributes are not compatibility promises; native cursor subclasses and their public interfaces are.

## Decisions

### 1. Expose one cursor API

Synchronous find/aggregate return their respective cursor types. Async find becomes a regular method returning `AsyncCursor`; async aggregate remains awaited and returns `AsyncCommandCursor`. Keep the current document-only generics and give these methods precise native cursor return annotations. No manager configuration or mode-dependent coroutine union is required.

The find facade mirrors native `Collection.find()`'s variadic argument shape rather than copying the driver cursor constructor's option signature. Native construction binds and validates all installed-driver positional and keyword options; static annotations preserve the cursor and document types. Copying the constructor signature would introduce a second version-sensitive option inventory and impose stricter static argument checks than the native collection method.

Eager consumers materialize the cursor explicitly with `list(cursor)` or synchronous `cursor.to_list()`, or `await cursor.to_list()` asynchronously. This completes the same consumption and admission path as iteration. For async aggregate, first await the method, then materialize its returned cursor.

**Alternative:** Preserving an eager list mode would retain two API contracts and require mode-aware generics, async dispatch, and duplicated consumer documentation. No independent durable compatibility requirement justifies that cost. Explicit materialization gives eager callers the required result without a permanent compatibility branch.

### 2. Use native cursor subclasses with localized integration

Add synchronous and asynchronous cursor modules. Find adapters subclass `Cursor`/`AsyncCursor`, initialize through native argument validation, and keep native query state, chaining, and batching. An execution hook performs eligibility and lookup just before the first query would execute, using the final validated shape. Eligible misses use the existing primary/majority profile; bypasses keep the caller's options. Public find `collection` identifies the wrapped native collection.

Command adapters subclass `CommandCursor`/`AsyncCommandCursor`. For eligible misses, a localized helper uses the driver's aggregation cursor factory and native temporary-session/retry envelope so the adapter owns its actual first batch, address, session, and cursor identifier. PyMongo's `_aggregate(..., cursor_class, ...)` supplies this seam in the inspected driver. Bind admission context per call, without mutable class-level or global context. Do not copy a live cursor's private state.

Bind the collector with a scoped `partial()` factory for the module-level command cursor class. The driver only invokes the factory despite annotating it as a class; confine the corresponding type cast to the integration helper. The returned cursor must not retain the factory or a dynamically created class that closes over the collector. Closing or exhausting it must release the collector object even while the cursor itself remains reachable; verify object lifetime rather than only a cleared field.

Aggregation hits create an isolated local command cursor with identifier zero and no address/session. Native local argument constraints must be validated through command preparation before selecting a hit, including pipeline shape, positional binding, unsupported explain, and malformed options. Bypasses use public native `aggregate()` unchanged. No initial command is deferred until a later cursor method.

Keep protected driver access in the integration helpers, document the accessed seams, and check the minimum supported and locked driver versions. Do not patch PyMongo globally, replace an object's class, duplicate the wire protocol, or silently switch return shape when integration fails.

**Alternatives:** A plain iterator breaks native type checks and methods. An eager cursor-shaped wrapper loses laziness and streaming. Copying a live native cursor risks duplicated connection/session ownership.

### 3. Distinguish preparation from later cursor operations

Use the driver as the behavior oracle, including inherited APIs and Python protocols. Treatment is:

| Operation                                                                                   | Cache treatment                                                                                                                                                                               |
| ------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Iteration, next, to_list, command try_next                                                  | Consume the selected snapshot or native cursor; all consumption paths share capture state.                                                                                                    |
| Find sort, skip, limit, collation                                                           | Update native query state before execution; derive the key afterward.                                                                                                                         |
| Find batch_size argument or pre-execution batch_size()                                      | Bypass lookup/admission and preserve native batching and validation.                                                                                                                          |
| Aggregate batchSize supplied at invocation                                                  | Bypass lookup/admission; execute the initial command before returning the cursor.                                                                                                             |
| Later CommandCursor.batch_size(), including async command cursors                           | Validate natively and return the same cursor. A native miss/bypass changes future getMore batching without changing admission eligibility; a local hit remains local with no batching effect. |
| Hint, comment, timeouts, min/max, disk-use options, flags, where, other unsupported options | Bypass using the original arguments rather than skipping required server behavior.                                                                                                            |
| Find explain or cursor distinct                                                             | Execute the native operation with its query/options.                                                                                                                                          |
| Clone, copy, rewind                                                                         | Start independent consumption and capture; recheck current eligibility and generations.                                                                                                       |
| Sync indexing/slicing                                                                       | Preserve native query rewriting and errors; changed queries have distinct keys.                                                                                                               |
| Async indexing                                                                              | Preserve native rejection.                                                                                                                                                                    |
| Close/context exit                                                                          | Release incomplete candidates and private buffers; clean up native resources.                                                                                                                 |

The [command-cursor batching API](https://pymongo.readthedocs.io/en/stable/api/pymongo/command_cursor.html#pymongo.command_cursor.CommandCursor.batch_size) updates subsequent batching after aggregation has already chosen its execution. It cannot retroactively force a local hit to execute a remote aggregate without violating initial-command timing. Test valid, invalid, repeated, and post-consumption calls on native and local cursors; never restart the query to accommodate a later batch setting.

Preserve native post-execution chaining errors, also on hits. Use the existing order-sensitive keys and codec fingerprints. Normalize defaults only when native validation establishes equivalent behavior. Resolve effective sessions at the native execution boundary, including bound contexts changed between find construction and consumption. Stream health, collection metadata, and manager state must be checked when execution begins rather than frozen at cursor construction.

### 4. Capture bounded snapshots using existing BSON primitives

Use one shared collector for the two execution models. Snapshot each delivered document through the existing BSON encoder before exposing it to caller mutation. Retain immutable per-document snapshots and count their total encoded payload against `max_entry_bytes`; do not retain an additional growing list of caller-owned documents or repeatedly serialize the entire prefix. The snapshot-envelope overhead makes this a conservative capture budget, distinct from the final stored-entry weight.

Start with library-provided snapshot and raw-document primitives. For example, `encode_value(document, codec_options)` provides an immutable snapshot, and BSON's `RawBSONDocument` can expose that snapshot's nested document to the ordinary list encoder without applying application decoders and encoders a second time. Use a raw-document codec context without custom transformations while accessing the snapshot envelope. At full consumption, pass the private captured documents to the existing `admit_namespace()` path and let its `bson.encode()` produce the list envelope and enforce the exact final entry size. No new encoded-admission API or manual array framing is required.

Preserve codec behavior, BSON types, field order, UUID representation, and document-class behavior through semantic comparisons with ordinary native/cache round trips. If a returned document cannot be snapshotted faithfully, abandon capture while continuing the native stream. Release capture state on oversize, close, error, or cancellation. The current document encoding and finalization can allocate transient buffers; fragment wrappers and allocator overhead are not covered by the encoded-payload budget. Measure actual heap peaks during finalization instead of promising a two-buffer memory limit.

An extra library encode/copy during finalization is acceptable initially. Candidate work remains linear in consumed result size. Profile that baseline before considering serializer changes; manual BSON assembly is not a task or acceptance criterion in this change. Any later optimization needs a measured bottleneck, comparison against this baseline, and separate justification for its codec/maintenance cost.

**Alternatives:** Keeping mutable caller references allows later mutation to poison admission. Whole-prefix re-encoding is quadratic. A custom incremental array assembler expands the serializer surface without evidence that existing BSON primitives are inadequate.

### 5. Admit after consumption, independently of server cleanup

Track unevaluated, native bypass, collecting miss, local hit, completed, and abandoned states. Capture generations immediately before the first native command after eligibility checks. Admit once only after every delivered document has been consumed and successful exhaustion is known. Empty results can be admitted; negative limits and single-batch completion are complete only for their final query.

Both next and batch-draining to_list must snapshot documents before returning them. Bounded to_list can leave a candidate in progress. Server cursor closure at the final batch does not imply that unread local documents were consumed. A transient empty batch or try_next returning None is not completion while a server cursor remains alive.

Errors and cancellation discard incomplete candidates and propagate the native outcome. Await native cleanup on async cancellation. Early close/context exit releases state without draining. Manager closure prevents admission and cannot reactivate streams, but does not take ownership of caller clients or independently owned native cursors.

### 6. Keep a started hit as an isolated snapshot

Use the existing isolated lookup result as the hit's private buffer. A find hit loads that snapshot into its local result buffer and reports retrieved as the loaded document count. Hit metadata is cursor_id zero, address/session None, and alive reflecting remaining documents. Hits allocate no server session and issue no killCursors command.

A new execution checks current eligibility and generations. After a hit starts, invalidation, stream uncertainty, eviction, or manager closure cannot mix fresh documents into its result. Clone/rewind start new executions and cannot carry the old snapshot forward. Closing releases the local buffer. Returned snapshots are caller-owned memory outside the LRU's stored-byte budget, as current returned lists are.

### 7. Measure the library-primitive baseline

Adapt eager assumptions in `benchmarks/stream_cost/{pair_runner,guard_workload,decision_evidence}.py`: cursor construction alone does not activate a stream, warm an entry, or measure admission. Consume results inside activation, correctness, and timing paths.

Compare native cursors with cached cursors using the same iteration or explicit materialization pattern. Cover sync/async find and aggregate, cold full consumption, verified hits, early close, naturally one/multiple batches, representative document sizes, capture/final-entry size boundaries, and concurrently open partial cursors. Cases requesting batching before execution are native bypass controls; use default native batching for eligible multi-batch cache cases.

Record first-document and total-consumption latency, throughput, CPU/profile hotspots, actual heap peaks, retained snapshot payload, query/getMore counts, and hit/admission outcomes. Assert correct results and origin-call counts before timing comparisons. Keep the existing performance guard thresholds; no new cursor-overhead threshold is justified yet.

Snapshot creation, final BSON encode/copy, hit decoding, and adapter dispatch are suspected costs, not measured bottlenecks. Retained snapshot payload is bounded by E per collecting cursor, but wrappers, native batches, current-document encoding, finalization, and decoded hit values consume additional memory. Concurrent collecting cursors can retain O(cursor count × E) payload outside the stored-entry budget. Measure these allocations rather than claiming E is a process-memory limit.

Store only `reports/cached-read-cursors/summary.md` with observed comparisons, environment, and reproduction commands. Keep raw output untracked and record important measurements in the implementation commit body.

## Risks / Trade-offs

- **Protected driver hooks can drift** → Localize integration, document its seams, and exercise PyMongo 4.18.1 and the locked version.
- **Snapshot round trips can change custom codecs** → Use library raw-document support, avoid replaying transformations, and compare codec-sensitive results to the native/cache baseline.
- **Idle cursors retain candidates** → Bound payload, release on close/error/cancellation, document context management, and measure concurrent partial cursors.
- **Finalization adds CPU and transient allocation** → Measure the simple library-primitive implementation before approving a serializer optimization.
- **Server cleanup can precede actual consumption** → Cover unread final batches and every native consumption path.
- **A started hit outlives invalidation** → Document snapshot consumption and recheck generations/health for new executions.

## Migration Plan

Change return annotations and consuming code in one implementation change. Convert synchronous eager calls to `list(collection.find(...))` or `collection.aggregate(...).to_list()`. Replace `await collection.find(...)` with `await collection.find(...).to_list()` when a list is required. For async aggregate, await aggregate first, then await its cursor's to_list.

Update public examples, API/consistency docs, README overview, and one changelog entry together. Explain local-hit batching, explicit materialization, and snapshot consumption without claiming whole-collection interchangeability. Existing eager tests should materialize cursors; do not retain list-mode fixtures or mode-dependent generics. Preserve the separate scope of active usage-example work when adapting its consumers.

No persistent cache migration is needed because caches are process-local and the existing list envelope and discriminators remain in use. A rollback reverts the feature commit; the public API has no compatibility setting to carry afterward.
