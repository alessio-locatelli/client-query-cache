# Spec Delta

## ADDED Requirements

### Requirement: Multi-document reads preserve native cursor call shapes

Synchronous `find()` and `aggregate()` SHALL return cursors directly, asynchronous `find()` SHALL return its cursor without awaiting, and asynchronous `aggregate()` SHALL return its cursor when awaited. Calls SHALL accept the corresponding PyMongo method's positional and keyword arguments.

#### Scenario: Shared synchronous read code

- **WHEN** the same function calls `collection.find(...).sort(...).skip(...).limit(...)` or iterates `collection.aggregate(...)` using a native collection and a cached view
- **THEN** both calls work without changing the consuming function

#### Scenario: Shared asynchronous read code

- **WHEN** the same async function uses `async for document in collection.find(...)` and `cursor = await collection.aggregate(...)` with either collection
- **THEN** both forms work without adding an await to `find()`

#### Scenario: Positional options are passed

- **WHEN** a caller uses positional options accepted by the installed PyMongo method
- **THEN** the cached method binds them with native argument semantics, including errors for duplicate arguments

### Requirement: Find cursor construction is lazy

`find()` SHALL perform native local argument validation at construction and defer database queries, metadata probes, stream activation, and cache lookup until consumption or another native operation requiring execution.

#### Scenario: A cursor is never consumed

- **WHEN** a caller constructs a valid `find()` cursor and closes it without executing it
- **THEN** no database read, metadata probe, stream activation, cache lookup, or admission is performed

#### Scenario: Invalid constructor options follow warming

- **WHEN** a caller constructs a cursor with locally invalid PyMongo arguments after warming a related valid query
- **THEN** the constructor raises the native validation error rather than returning cached data

### Requirement: Cursor types preserve native public interfaces

Results of `find()` and `aggregate()` SHALL be instances of the corresponding PyMongo `Cursor`, `AsyncCursor`, `CommandCursor`, or `AsyncCommandCursor` type, including permitted subclasses. Public methods SHALL retain their native return shapes, await conventions, and local validation errors.

#### Scenario: A caller checks the cursor type

- **WHEN** a caller receives a cold, warm, or bypassed cursor
- **THEN** `isinstance` against the corresponding native cursor class succeeds

#### Scenario: Native cursor operations are used

- **WHEN** a caller uses supported iteration, `next`, `to_list`, `close`, context management, or command-cursor `try_next`
- **THEN** the result and state transitions follow that native cursor interface

#### Scenario: Async indexing is attempted

- **WHEN** a caller indexes an async find cursor where PyMongo rejects indexing
- **THEN** the cached cursor preserves that rejection

### Requirement: Chaining determines the executed query

Find cursor cache identity SHALL reflect its final output-affecting options before execution. Options or operations outside the supported cache contract SHALL execute natively without cache lookup or admission.

#### Scenario: A chained query differs from its constructor

- **WHEN** a caller constructs `find({})` and applies sort, skip, limit, or collation before consuming it
- **THEN** results and cache identity reflect the final query rather than the constructor's original shape

#### Scenario: A native-only option follows a warm query

- **WHEN** a caller uses a hint, comment, timeout, arbitrary flag, or another option outside the supported cache contract
- **THEN** that option reaches PyMongo without reusing a warm entry that would skip its server behavior

#### Scenario: Chaining follows consumption

- **WHEN** a caller changes an option that PyMongo forbids changing after execution starts
- **THEN** the cached cursor raises the native error, including on a hit

#### Scenario: A caller asks for explain or cursor distinct

- **WHEN** a caller invokes `explain()` or the find cursor's `distinct()` method
- **THEN** that operation executes natively with its original options instead of answering from cached find documents

### Requirement: Cursor re-execution has independent state

Find cursor cloning, copying, rewinding, and synchronous indexing or slicing SHALL follow native query semantics with independent consumption and admission state for each resulting execution.

#### Scenario: A consumed cursor is cloned

- **WHEN** a caller clones a partially or fully consumed find cursor
- **THEN** the clone begins unevaluated with the same query options and does not reuse the original cursor's position or incomplete candidate

#### Scenario: A cursor is rewound

- **WHEN** a caller rewinds a find cursor and consumes it again
- **THEN** it starts a new execution that rechecks eligibility and current cache generations without replaying an obsolete private snapshot

#### Scenario: Synchronous indexing follows a limit

- **WHEN** a caller uses an integer index or slice on an unevaluated synchronous find cursor
- **THEN** native skip/limit semantics apply rather than indexing a list cached for a different query

### Requirement: Cursor misses stream without eager draining

On a miss or bypass, multi-document reads SHALL fetch through native batching as requested by the caller without draining remaining results or adding per-document remote calls for caching. Aggregation SHALL retain its native initial-command timing.

#### Scenario: Only the first document is requested

- **WHEN** a caller requests one document from a multi-batch miss and then stops
- **THEN** caching causes no getMore calls to drain remaining batches

#### Scenario: An aggregation cursor is requested

- **WHEN** a caller calls synchronous `aggregate()` or awaits asynchronous `aggregate()` on a miss or bypass
- **THEN** the initial aggregation command runs before the cursor is returned, and subsequent batches remain caller-driven

### Requirement: Cursor candidates have bounded storage

The encoded payload retained for a cursor's cache-admission candidate SHALL be bounded by the configured maximum entry size, excluding transient document encoding and finalization. Exceeding that size or being unencodable SHALL discard the candidate without truncating the returned stream. This payload bound SHALL NOT be presented as a process-memory limit.

#### Scenario: An oversized result is consumed

- **WHEN** the encoded candidate exceeds the entry-size limit before exhaustion
- **THEN** retained candidate storage is released, subsequent documents are delivered normally, and no result is admitted

#### Scenario: A returned value cannot be encoded

- **WHEN** candidate encoding cannot represent a successfully returned document
- **THEN** the cursor continues with native results without admitting that execution

### Requirement: Admission preserves documents before caller mutation

Cursor admission SHALL preserve each returned document's value before the caller can mutate it, and hits SHALL provide isolated mutable results for each cursor.

#### Scenario: An early document is changed before exhaustion

- **WHEN** a caller mutates the first delivered document and later consumes the rest of the cursor
- **THEN** a subsequent hit returns the original document value rather than the caller's mutation

#### Scenario: Two hit cursors are consumed independently

- **WHEN** a caller mutates a document from one hit cursor
- **THEN** another hit cursor and the stored entry retain their original values

### Requirement: A started hit retains one result snapshot

Once a cursor starts consuming a valid hit, its remaining documents SHALL come from that isolated result snapshot. Namespace invalidation, stream uncertainty, or manager closure SHALL prevent subsequent executions from reusing that entry without restarting or mixing the current cursor's result.

#### Scenario: A write invalidates a partially consumed hit

- **WHEN** invalidation occurs after a hit cursor has delivered its first document
- **THEN** the cursor finishes its original snapshot, and a new cursor cannot use the invalidated entry

#### Scenario: Stream health changes during a hit

- **WHEN** stream continuity becomes uncertain during a started hit
- **THEN** that cursor retains its snapshot, while new executions bypass cache use until health is restored

#### Scenario: A manager closes with a hit in progress

- **WHEN** the manager closes after a hit cursor has started
- **THEN** the cursor can finish its isolated snapshot without reopening streams or accessing the closed cache

### Requirement: Hit cursor metadata describes local results

Hit cursors SHALL report no live server cursor: `cursor_id` is zero, `address` and `session` are `None`, and `alive` reflects remaining local documents. Find cursors SHALL expose the wrapped native collection and report `retrieved` as documents loaded into their local result buffer.

#### Scenario: A nonempty hit is opened

- **WHEN** a caller starts a hit containing several documents
- **THEN** metadata identifies a local result, and find `retrieved` counts the loaded snapshot rather than only documents consumed

#### Scenario: A hit is closed or exhausted

- **WHEN** the caller closes the hit cursor or consumes its remaining documents
- **THEN** `alive` becomes false and no killCursors command or implicit server session is created for that hit

### Requirement: Cursor cleanup does not own the client

Closing a cursor or exiting its context SHALL release its native resources, private result buffers, and incomplete admission candidate without closing the caller-owned client. Async cancellation SHALL discard incomplete candidates and perform awaited native cleanup.

#### Scenario: A context exits early

- **WHEN** a caller exits a cursor context before full consumption
- **THEN** its incomplete candidate is released, native cursor resources are closed, and the client remains usable

#### Scenario: An async read is cancelled

- **WHEN** cancellation interrupts a cursor read
- **THEN** cleanup releases the candidate and native resources and propagates cancellation without admitting partial data

### Requirement: Batching options known before execution bypass caching

Find batch-size options selected before execution and aggregation `batchSize` options supplied at invocation SHALL bypass cache lookup and admission while retaining native validation, initial-command timing, and batching.

#### Scenario: A find cursor is configured before consumption

- **WHEN** a caller supplies find `batch_size` or calls `find(...).batch_size(...)` before execution
- **THEN** the cursor executes natively without a hit or admission, including when a related query is warm

#### Scenario: Aggregate receives an explicit batchSize

- **WHEN** a caller supplies `batchSize` to `aggregate()` on a warm query
- **THEN** the initial command executes before the cursor is returned, with native batching and no cache lookup or admission

### Requirement: Later command-cursor batching retains the selected execution

`CommandCursor.batch_size()` and its asynchronous counterpart SHALL retain native validation and return the same cursor without changing the already selected execution. On a native cursor it SHALL affect subsequent getMore operations; on a local hit it SHALL have no remote batching effect or trigger native execution.

#### Scenario: A local aggregation hit is configured

- **WHEN** a caller invokes `batch_size(...)` before or during consumption of a local aggregation hit
- **THEN** valid input returns the same cursor, invalid input raises the native error, and no aggregate or getMore command is issued

#### Scenario: A native aggregation cursor is configured

- **WHEN** a caller invokes `batch_size(...)` on a miss or bypass after the initial command has executed
- **THEN** subsequent getMore operations use the native batch setting without rerunning the initial command or changing that execution's admission eligibility

### Requirement: Cursor-only requests execute natively

`find()` SHALL delegate tailable, exhaust, and partial-result requests and `aggregate()` SHALL delegate `$changeStream` pipelines natively without cache lookup, admission, or eager materialization.

#### Scenario: A cursor-only find request is supplied

- **WHEN** a caller requests a tailable or exhaust cursor or enables partial results
- **THEN** the caller receives the corresponding native cursor or native error without eager draining or caching

#### Scenario: An aggregation pipeline requests a change stream

- **WHEN** a caller runs a `$changeStream` pipeline
- **THEN** PyMongo supplies the native command cursor or native error without cache lookup or admission

## MODIFIED Requirements

### Requirement: Raw access exposes overridden PyMongo methods

The `.raw` property SHALL expose the exact wrapped PyMongo object for calls requiring PyMongo semantics, including calls whose names are overridden by cache-aware reads.

#### Scenario: A caller needs PyMongo's own semantics for an overridden method name

- **WHEN** a caller needs native execution of `find_one`, `find`, `aggregate`, `count_documents`, `estimated_document_count`, or `distinct`, even when a cached entry exists
- **THEN** the caller reaches the wrapped PyMongo object through `.raw` and calls the method there, bypassing the facade's override entirely

### Requirement: Incomplete results are not admitted

The facades SHALL admit only complete, bounded results of supported reads after successful consumption, guarded by the namespace and stream-availability generations captured before native execution.

#### Scenario: A caller abandons a cursor

- **WHEN** a caller partially consumes a cacheable-looking cursor
- **THEN** the facade does not admit its incomplete result to the cache

#### Scenario: The server exhausts before the caller consumes its batch

- **WHEN** the server cursor is exhausted but the caller leaves delivered batch documents unread
- **THEN** the facade does not admit the unread result

#### Scenario: Bounded to_list calls consume only a prefix

- **WHEN** a caller requests a prefix with `to_list(length=...)` and leaves documents unread
- **THEN** no entry is admitted until later calls consume the complete result

#### Scenario: An empty result is fully consumed

- **WHEN** a supported read successfully establishes that it has no documents
- **THEN** its empty result can be admitted under the same generation guards

#### Scenario: Execution fails after delivering documents

- **WHEN** a later batch raises a native error or cancellation interrupts execution
- **THEN** the incomplete result is not admitted and the error or cancellation propagates

#### Scenario: An invalidation or stream transition races consumption

- **WHEN** a write, namespace change, stream availability transition, or manager closure occurs between capture and full consumption
- **THEN** the result is not admitted under the obsolete capture

## REMOVED Requirements

### Requirement: Change-stream aggregation is rejected

**Reason**: Aggregation returns a cursor and no longer needs to reject an unbounded pipeline to prevent eager materialization.

**Migration**: `$changeStream` pipelines execute natively through `aggregate()` without caching; `.raw.aggregate()` remains available for explicit native execution.
