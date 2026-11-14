# Architecture

This guide describes the process-local manager and the native cache core that serves both execution models and the shared owner. The [shared-cache reference](shared-cache.md) covers native mappings, ownership and publication. Public contracts live in the [API reference](../user/reference/api.md), [consistency guide](../user/usage/consistency.md), and [operations guides](../user/operations/index.md).

## High-level design

```text
your application code
        │
        ▼
CachedCollection / CachedDatabase   (view: find_one, find, aggregate, count_documents,
        │                            estimated_document_count, distinct — everything else
        │                            called on the PyMongo object or `.raw`)
        ▼
   CacheManager                     (one per MongoClient/AsyncMongoClient you want cached)
        │
        ├── CacheCore               (native: bounded in-memory storage, hit/miss/eviction bookkeeping)
        │
        └── ChangeStreamCoordinator (one DatabaseStreamSupervisor per active cached database)
                    │
                    ▼
        MongoDB change stream(s)    (one cursor per active cached database)
```

A read against a `CachedCollection` either returns a cached value, executes against MongoDB and admits the result
to the cache, or bypasses the cache entirely and executes a normal PyMongo call — see the [cached-read guide](../user/usage/cached-reads.md) for the public behavior. `ChangeStreamCoordinator` starts one `DatabaseStreamSupervisor` per database the first time a
read touches it; each supervisor watches that one database and invalidates affected cache entries in the native cache core as
writes and schema changes occur. The public `CacheCore` is the Rust `LocalCacheCore` in
`native/shared-index/src/local_cache.rs`; the shared owner uses its `SharedOwnerCore` extension
(`local_cache/shared.rs`). `_core/native.py` supplies configuration, codec, key, error and snapshot
integration, and `_core/contracts.pyi` types the interface both cores implement.

## Low-level design

- **Cursor snapshot ownership**: `CursorCapture` encodes each consumed document once through
  `encode_value()` before the caller can mutate it and appends the bytes to a native
  `EncodedArray`, which tracks the retained envelope size against the entry limit.
  Finalization passes the finished BSON list to `CacheCore.admit_namespace_encoded()`, which
  applies exact entry weighting, eviction, and generation guards. Abandonment and
  finalization release the retained snapshots.
- **Cursor allocation budgets**: the collector bounds the sum of encoded document envelopes
  by `max_entry_bytes` per collecting cursor. Counting the envelope overhead is conservative
  relative to the retained nested document bytes. The final stored list has its own envelope
  and array keys and must pass the ordinary exact entry-size check. Stored cache bytes,
  retained candidate payload, native decoded batches, raw-document wrappers, temporary
  document encoding, and final BSON encoding/copying are separate allocations. Concurrent
  collectors can retain payload proportional to cursor count times `max_entry_bytes` outside
  the cache's shared stored-byte budget. Actual heap peaks require allocation measurements;
  the encoded-payload bound alone does not bound process memory.

- **Session context**: before cache lookup or admission, both cached collections ask the shared request classifier
  to bypass explicit sessions and sessions bound by `ClientSession.bind()` or `AsyncClientSession.bind()`.
  PyMongo exposes no public accessor for the effective session, so the guard feature-detects
  the private `_get_bound_session` callback. An unavailable or non-callable callback
  conservatively bypasses all cached reads. Its behavior is checked against PyMongo 4.18.1 and 4.18.2. An explicit
  non-`None` session takes precedence. If private inspection raises an ordinary exception, the classifier bypasses and
  lets the original native operation validate its arguments and session; this preserves native error ordering. Cancellation and process-control exceptions propagate.
  The resolver reads local context only and issues no database commands.
- **Cache granularity**: entries are scoped to a MongoDB namespace (`database.collection`), then further scoped
  within it. A `find_one` filter that pins `_id` to an exact value under simple collation, alone or with additional
  predicates, or resolves through a qualifying unique index is
  cached and invalidated per document, so a write to one document never invalidates another document's cached
  entry. Document identities compare by value as MongoDB compares them, so a write to a document whose stored
  `_id` is the decimal `1` invalidates a cached read by the integer `_id` `1`. Every other eligible `find_one` filter, and every `find`, `aggregate`, `count_documents`, `distinct` and
  `estimated_document_count` result, is
  cached and invalidated as a whole namespace: any write to that collection invalidates every such cached result for
  it, regardless of which document the write touched.
- **Unique-key discovery**: the facade discovers which fields can resolve a single-document lookup from the
  collection's own index metadata (a plain, non-partial, non-sparse, non-hashed unique index whose collation matches
  the read) — there is nothing to declare, and discovery is re-checked whenever an index is added or removed.
- **Coherency model**: coherency is eventual, not synchronous. A cache hit may still return the pre-write value, even after the write has returned, until this library's change-stream worker processes that write's event; once processed, every later read is guaranteed to see the invalidation. This is not a per-write barrier — it does not wait for "catch-up" on every read, only guarantees that a processed write is never silently missed.
- **Stream availability ownership**: the cache core records whether a database's change stream is healthy as one flag per database, not one flag per coordinator that might be watching it. If two coordinators shared a cache core, one of them starting, losing its stream, or stopping would overwrite that shared flag and could mark another, still-healthy coordinator's database unavailable. Cached reads for that database would then bypass with no error or warning pointing at the actual cause, so the [API reference](../user/reference/api.md#ownership) makes such sharing unsupported.

## Read key preparation

The sync and asyncio facades use `_core.read_classification.prepare_query_key()`
for count, distinct, and find, and `prepare_pipeline_key()` for aggregation.
Request-level bypass checks precede these helpers; filter safety precedes
projection safety, and pipeline safety precedes pipeline key preparation.
The helpers return a canonical key and a bypass reason. Callers branch on the
reason because `None` can also be a successful key. A preparation failure
records one facade bypass and delegates with the native arguments before any
collection eligibility probe.

Native key preparation handles plain scalars, mappings and sequences itself. Custom mapping and
sequence subclasses, and leaves without a compact native form, reach the generic Python
implementations in `_core/canonical.py` and `_core/order_sensitive_keys.py`
(`_generic_canonicalize` and the `_generic_order_sensitive_*` functions); `read_validation.py`
supplies the same kind of delegate for unsafe-construct scans. Production reads call these
delegates, and the tests check that the native fast paths agree with them.

Count and distinct retain the prepared discriminator through lookup and
admission. Aggregation retains it in `CursorCapture` until complete consumption
allows `finish()` to attempt admission. Core entry points continue to accept
raw keys; canonical tagged inputs pass through by identity without rebuilding
their trees.

## Cursor driver integration

Both find cursor paths build exact and limit-independent identities through
`_core.find_reads.find_read_shape()` from the same final native fields, preserving
the executed filter representation. `_core.query_filters.find_filter_key()`
sorts top-level scalar equality predicates only for plain dictionaries whose
field names are exact built-in strings not starting with `$` and whose values are `None` or
exact built-in bool, int, float, or str instances. A private tag separates this
representation from ordered fallback, and existing numeric value tags retain
bool/int/float/BSON Int64 distinctions through full key canonicalization.
Documents, arrays, operators, BSON scalars, regexes, and custom forms use the
unchanged order-sensitive representation. The helper performs no recursive
semantic classification and never rewrites the native `_spec`; eligibility
still examines the original query. Lookup, limit-family membership, and capture
admission share the same filter representation. Other read methods do not use
this helper. [Differential semantic evidence](../../reports/query-filter-normalization/summary.md)
record the tested MongoDB/PyMongo versions and limitations.
Only non-boolean integer limits at least zero
produce `FindSource` admission metadata; zero denotes an unlimited source.
The native core keeps, for each namespace, the resident sources of each query
family ordered by limit. A source descriptor retains only the family hash and the
limit; the complete canonical query belongs to the exact key. Lookup compares that
key against the requested family and candidate limit, so hash collisions cannot
reuse a different query. Each find execution prepares the final native shape's
family once and places the canonical family in a local `FindReadShape`.
`find_discriminator()` wraps this same family for capture admission,
`lookup_find()` reuses it for exact and candidate keys, and `shape.source` hashes
it for source metadata. Canonical passthrough takes constant time; wrappers do not
rebuild the raw family. Hashing and equality can still inspect the canonical tree.
Rewind and clone prepare their final native options again on the next execution.
Payload bytes are the stored entries; the BSON budget excludes query keys and
native index overhead. Displacement, eviction, invalidation, clear, drop and close
remove sources together with their entries, and removal never takes a newer
replacement.

`lookup_find()` checks availability, probes the exact key, then inspects only the
requested hash bucket for a positive non-boolean limit. It collects the sources
whose limit covers the request, in increasing order with unlimited last, and
chooses the first whose full query key matches; that entry must still be current
when it is served. Writes, clear and create empty a namespace's family index, so
invalidated sources are not candidates. One lookup records one hit or miss, or the
existing availability bypass. Discovery visits the k resident sources of the family
using only scalar limits; unrelated families do not expand candidate inspection. A
valid smallest source requires one full key comparison, regardless of admission
order. Hash collisions can require more comparisons, each depending on query size.

Hits decode the full BSON list through the requesting codec, then install only
the requested prefix. Decoding costs O(source bytes) CPU and transient memory;
the private cursor buffer holds at most the requested document count. Hits create
no admission capture or additional resident payload. The validity decision is the
existing snapshot boundary: later invalidation cannot retract a started cursor.

The synchronous and asynchronous `cursors.py` modules confine protected PyMongo
access to the native execution and aggregation factory boundaries. Find subclasses
preserve `Collection.find()`'s variadic argument shape, with native constructor
validation and precise cursor/document return annotations. They
use `_refresh()` for final-query preparation, `_send_message()` to distinguish
internal server-resource cleanup from caller close, `_next_batch()` for `to_list()`,
and `_clone_base()` for independent captures. Final keys read the native `_spec`,
`_projection`, `_ordering`, `_skip`, `_limit`, `_collation`, and codec fields;
unsupported flags and query options retain native execution. Local find hits set
the native `_data`, `_retrieved`, `_id`, and `_killed` buffer state. Eligible misses
set the primary/majority read profile without replacing the wrapped collection.

Aggregation preparation uses `_CollectionAggregationCommand` for local argument
validation before lookup. Misses use `Collection._aggregate()` with a scoped
`partial()` factory for the module-level cursor class inside the native client
`_tmp_session()` envelope, preserving
retry, session, first-batch, and connection ownership. No live cursor is copied.
The returned cursor does not retain the factory; releasing its capture field
also releases the collector object, without waiting for cursor collection.
Command subclasses capture `_try_next()` and `_next_batch()` consumption; empty
results also finalize through `next()` and `to_list()`. Native command batching is
inherited unchanged, including on local hits. Internal final-batch `close()`
releases server resources while retaining unread documents and capture state;
caller close releases both. Errors discard capture, and async cancellation awaits
native cleanup before propagating.

Native iteration/context protocols, supported chaining, indexing validation,
explain/distinct, and command batching remain inherited except for these localized
hooks. Copy/clone and rewind start independent executions. Hits have no server
cursor, address, or session; find `retrieved` counts the loaded snapshot or prefix.
Both execution models are checked with the same disposable replica-set cursor and
bound-session cases on PyMongo 4.18.1 and the locked 4.18.2 driver. Future driver
releases require the same differential checks because these hooks are protected.

Process-local managers use `LocalCacheCore` from the extension, and shared-cache coordination uses `SharedOwnerCore`, which adds publication to the shared index and payload arena. Both implement the common read and coherence protocols; their capture objects are opaque handles. The [native evaluation report](../../reports/native-process-local-cache/results.md) records measured costs and adoption evidence.

## Core verification

The `tests/core/` contract tests construct the production native core (`LocalCacheCore`, and `SharedOwnerCore` where a behavior applies to it) and assert explicit outcomes: admission results, lookup hits, snapshots, alias resolution and object lifetime through weak references. No second cache implementation serves as an oracle. Generated schedules in `test_manager_state_machine.py`, `test_find_limit_subsumption.py` and `test_native_owner.py` keep only a record of the values each operation was admitted with, and assert that a hit never returns a value older than the latest write, clear, drop or availability transition affecting its key and that the budget holds. They do not predict which entries eviction removes.

Collision and race cases use keys whose equality callbacks re-enter or block the core, because the native owner runs those callbacks outside its critical sections. Native synchronization is checked by the unit and Loom models under `native/shared-index/` (`just rust-tests`).
