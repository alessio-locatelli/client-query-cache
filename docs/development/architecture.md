# Architecture

This guide describes the internal cache and invalidation design. Public contracts live in the [API reference](../user/reference/api.md), [consistency guide](../user/usage/consistency.md), and [operations guides](../user/operations/index.md).

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
        ├── CacheCore               (bounded in-memory storage, hit/miss/eviction bookkeeping)
        │
        └── ChangeStreamCoordinator (one DatabaseStreamSupervisor per active cached database)
                    │
                    ▼
        MongoDB change stream(s)    (one cursor per active cached database)
```

A read against a `CachedCollection` either returns a cached value, executes against MongoDB and admits the result
to the cache, or bypasses the cache entirely and executes a normal PyMongo call — see the [cached-read guide](../user/usage/cached-reads.md) for the public behavior. `ChangeStreamCoordinator` starts one `DatabaseStreamSupervisor` per database the first time a
read touches it; each supervisor watches that one database and invalidates affected cache entries in `CacheCore` as
writes and schema changes occur.

## Low-level design

- **Cursor snapshot ownership**: `CursorCapture` encodes each consumed document once through
  `encode_value()` before the caller can mutate it. It accesses the nested snapshot with
  `RawBSONDocument` using a codec context without application transformations. Finalization
  passes these private raw documents to `CacheCore.admit_namespace()`, which retains its
  normal BSON list envelope, exact entry weighting, eviction, and generation guards.
  Abandonment and finalization release the retained snapshots.
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
  within it. A read resolved to one document — by `_id`, or by a value in a field a unique index enforces — is
  cached and invalidated per document, so a write to one document never invalidates another document's cached
  entry. Document identities compare by value as MongoDB compares them, so a write to a document whose stored
  `_id` is the decimal `1` invalidates a cached read by the integer `_id` `1`. A read with no such resolved identity (a generic `find_one` query or a bounded `find`/`aggregate`/`count_documents`/`distinct` result) is
  cached and invalidated as a whole namespace: any write to that collection invalidates every such cached result for
  it, regardless of which document the write touched.
- **Unique-key discovery**: the facade discovers which fields can resolve a single-document lookup from the
  collection's own index metadata (a plain, non-partial, non-sparse, non-hashed unique index whose collation matches
  the read) — there is nothing to declare, and discovery is re-checked whenever an index is added or removed.
- **Coherency model**: coherency is eventual, not synchronous. A cache hit may still return the pre-write value, even after the write has returned, until this library's change-stream worker processes that write's event; once processed, every later read is guaranteed to see the invalidation. This is not a per-write barrier — it does not wait for "catch-up" on every read, only guarantees that a processed write is never silently missed.
- **Stream availability ownership**: a `CacheCore` records whether a database's change stream is healthy as one flag per database, not one flag per coordinator that might be watching it. If two coordinators shared a `CacheCore`, one of them starting, losing its stream, or stopping would overwrite that shared flag and could mark another, still-healthy coordinator's database unavailable. Cached reads for that database would then bypass with no error or warning pointing at the actual cause, so the [API reference](../user/reference/api.md#ownership) makes such sharing unsupported.

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
this helper. [Differential evidence and measurements](../../reports/query-filter-normalization/summary.md)
record the tested MongoDB/PyMongo versions and limitations.
Only non-boolean integer limits at least zero
produce `FindSource` admission metadata; zero denotes an unlimited source.
Each namespace's `find_families` maps compact family hashes to actual resident
entry tokens and their physical keys. Source descriptors retain only the hash
and limit; the complete canonical query belongs to the exact physical key.
Lookup compares that key against the requested family and candidate limit before
probing, so hash collisions cannot reuse a different query. Shape construction
shares one query tree between the raw family and exact discriminator. Payload
bytes belong solely to the LRU entries; the BSON budget excludes query keys and
Python index overhead.
Admission publishes tokens alongside `entry_index` through `_finalize_put()`;
displacement, eviction, and post-publication reclamation remove the exact token
without removing a newer replacement. Writes clear family buckets as they advance
the generation; clear/create reclaim them with the namespace, and close releases
the namespace registry.

`lookup_find()` checks availability, probes the exact key, then snapshots only
the requested hash bucket for a positive non-boolean limit. Outside both locks,
it orders candidates by increasing positive limit, with unlimited last, then
checks full query identity, resident token identity, and the actual entry
generation before choosing the smallest covering positive limit, with unlimited
as fallback. It stops at the first valid match;
failed candidates do not hide valid sources. Namespace and LRU sections remain
separate: snapshot/validity decisions
hold the namespace lock, while entry probes and source promotion hold the LRU lock.
One lookup records one hit or miss, or the existing availability bypass. Discovery
orders k resident sources in O(k log k) time using only scalar limits; unrelated
hashes do not expand candidate inspection. A valid smallest source requires one
full key comparison and one source probe, regardless of admission order. Failed
candidates or hash collisions can require more comparisons, each depending on
query size. Publication and removal have expected O(1) token cost. Core ownership/race tests
and generated operation schedules live in `tests/core/test_find_limit_subsumption.py`.

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
