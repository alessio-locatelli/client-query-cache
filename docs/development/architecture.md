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
  entry. A read with no such resolved identity (a generic `find_one` query or a bounded `find`/`aggregate`/`count_documents`/`distinct` result) is
  cached and invalidated as a whole namespace: any write to that collection invalidates every such cached result for
  it, regardless of which document the write touched.
- **Unique-key discovery**: the facade discovers which fields can resolve a single-document lookup from the
  collection's own index metadata (a plain, non-partial, non-sparse, non-hashed unique index whose collation matches
  the read) — there is nothing to declare, and discovery is re-checked whenever an index is added or removed.
- **Coherency model**: coherency is bounded and eventual, not synchronous. A cache hit that runs concurrently with
  an independent write may still return the pre-write value until this library's change-stream worker processes
  that write's event; once processed, every later read is guaranteed to see the invalidation. This is not a
  per-write barrier — it does not wait for "catch-up" on every read, only guarantees that a processed write is never
  silently missed.
