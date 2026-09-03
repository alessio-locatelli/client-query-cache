## Context

See [proposal.md](proposal.md) for the motivation. The existing proof of concept
subclasses synchronous PyMongo objects, retains query results in unbounded
Python dictionaries, and runs one collection watcher in a daemon thread. Its
update, replace, and rename handlers raise `NotImplementedError`; no code
persists a resume token or handles an unresumable stream. Existing tests cover
basic synchronous calls but do not establish external-writer invalidation or
recovery behavior.

MongoDB change streams are available on replica sets and sharded clusters, can
watch a database, and require a retained connection while waiting for events.
Change notifications are majority committed. Resume tokens only work with the
same pipeline/options and only while the necessary oplog history remains.
These constraints come from the [MongoDB change-stream documentation](https://www.mongodb.com/docs/manual/changeStreams/).

The official PyMongo asyncio API became generally available in PyMongo 4.13,
which permits one driver family for synchronous and native asyncio support. See
the [PyMongo release notes](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/reference/release-notes/).

## Goals / Non-Goals

**Goals:**

- Build a stable composition-based boundary that can add cache backends and
  safely supported read operations without replacing the public architecture.
- Cache all useful fully materialized client-side read shapes with either
  fine-grained identity eviction or correct coarse invalidation.
- Make a stale cache less available, never more available, when change-stream
  continuity is uncertain.
- Provide a development-safe and production-safe in-memory default, complete
  operating guidance, and measurable cache behavior.

**Non-Goals:**

- Replace Redis or provide shared cache state across processes.
- Preserve cache entries or resume tokens across process restarts.
- Cache session-bound reads, transactional reads, tailable/exhaust cursors, or
  arbitrary PyMongo operations whose semantics are not explicitly supported.
- Promise linearizable reads or hide MongoDB replication and change-stream
  latency behind an "always consistent" claim.

## Decisions

### Composition facades around a shared manager

Synchronous and asyncio database/collection facades will wrap, rather than
subclass, PyMongo objects. A cache manager owns the backend, a single
database-level stream supervisor, lifecycle, and resource budget. Collections
obtained from that manager share it.

```text
sync facade                asyncio facade
    |                           |
    +-------- cache manager ----+
                 |       |
           memory store   database stream supervisor
```

Subclassing presents all PyMongo methods as equally supported and ties the
library to driver internals. Separate sync/async facades retain idiomatic driver
behavior while sharing policy and test cases.

### Two cache planes, chosen by invalidation proof

The document plane maps `_id` and declared unique-key aliases to a document.
Each identity points to the same document record, so any event with its
document key evicts all aliases.

The derived-result plane stores complete results for `find`, `aggregate`,
counts, distinct values, and non-identity `find_one` calls. It does not attempt
to decide whether an event changes a filter, ordering, projection, limit, or
aggregation. Every database event advances a derived-result generation; an
entry is usable only when its generation equals the current generation.

```text
change event for db.orders
    |-- document key known --> evict document and aliases
    +-- any database event --> advance derived-result generation
```

This is deliberately coarse, but it makes arbitrary materialized MongoDB read
shapes correct without speculative query analysis. Collection drops and renames
also advance namespace generations so an `_id` cannot survive a drop/recreate
cycle.

### Majority-primary cache admission

Change streams announce majority-committed changes. Cacheable facade reads will
therefore use `PRIMARY` read preference and `MAJORITY` read concern. MongoDB
documents that secondary reads can be stale; the official guidance for avoiding
stale reads is primary preference with majority concern. See [MongoDB read
preference guidance](https://www.mongodb.com/docs/manual/core/read-preference-use-cases/).

The facade intentionally strengthens cacheable-read semantics instead of
silently caching a local or secondary read that could outlive its source value.
Session-bound and otherwise incompatible reads bypass both cache lookup and
admission. This is a documented boundary, not an error.

### Race-safe cache admission

Before a database read begins, the manager captures the relevant document and
derived-result generations. Admission takes a lock, verifies the generations
still match, and then records the entry. Event handling takes the same lock
before eviction or generation advancement. A result that lost this race is
returned to its caller but is not cached; an optional retry may obtain a value
eligible for admission.

### Explicit lifecycle and fail-closed cache use

The manager has `STARTING`, `HEALTHY`, `RECOVERING`, and `CLOSED` runtime
states. Startup is explicit so a deployment can surface a missing change-stream
privilege or unsupported topology before serving traffic. Such persistent setup
errors retain their original exception and are not converted into a silent
no-cache mode.

Temporary network, election, and resumable stream failures put the manager in
`RECOVERING`: reads go directly to MongoDB and do not populate the shared cache.
The supervisor retries using bounded exponential backoff with jitter and the
latest resume token. If resumption is rejected, an invalidation event closes the
stream, or another continuity guarantee is lost, the manager clears affected
entries and opens a new stream before returning to `HEALTHY`.

The in-memory backend starts empty on process startup, so persisted resume
tokens are unnecessary for the initial process-local backend. A future
persistent backend must persist cache data, token, stream configuration, and a
recovery protocol atomically; it cannot reuse this assumption.

### Bounded BSON LRU store

The default backend uses one 64 MiB weighted LRU budget per manager and rejects
entries larger than 1 MiB. It stores BSON bytes, not caller-owned Python
objects, and decodes a fresh result for every hit. The budget includes entry and
index metadata. The defaults are safe ceilings rather than sizing advice:
applications lower or raise limits based on their process memory budget and
observed BSON sizes.

No background eviction thread is needed; insertions, invalidations, and clear
operations maintain the index under the manager lock. Large results are returned
but are not admitted, preserving correctness without risking cache pressure.

### Observability through inspection and structured logging

The manager exposes a cheap inspection snapshot containing lifecycle state,
last recoverable error, capacity, and counters. It emits structured log records
through the standard library for lifecycle transitions and errors. This avoids a
mandatory metrics dependency while letting applications adapt the snapshot to
their own metrics system.

## System Requirements

| Area | Requirement |
| --- | --- |
| Runtime | CPython 3.13+; synchronous and native asyncio PyMongo facades. |
| Database | MongoDB replica set or sharded cluster with change-stream access; a standalone server cannot provide the coherency contract. |
| Permissions | `find` and `changeStream` on every cached collection; database-scoped watching requires those privileges across its non-system collections. |
| Read semantics | Cacheable reads use primary preference and majority concern; sessions and incompatible semantics bypass. |
| Resources | One held stream connection per active database manager, plus bounded process-local cache memory. |
| Lifecycle | Applications start and close managers explicitly in the appropriate sync or async application lifecycle. |
| Security | Never place connection strings, credentials, or document values in cache lifecycle error logs. |

## Capacity Estimation

Let `B` be the configured manager byte budget, `E` the maximum entry size, and
`S` the observed encoded BSON size of a candidate value plus cache metadata.
An entry is eligible only when `S <= E`; the retained working set is at most
approximately `B / median(S)` entries, subject to LRU metadata and document
aliases. The default 64 MiB budget is a hard ceiling for retained cache data,
not a statement about total process memory.

For a service with `M` managers in one process, reserve at least `M * B` for
their configured cache ceilings and then leave headroom for Python, PyMongo,
request concurrency, and MongoDB result materialization. Size `B` from a memory
limit, not user count. Measure hit rate, evictions, rejected oversize entries,
and BSON value percentiles under representative traffic before increasing it.

Database stream capacity is one long-lived `getMore` connection per manager.
MongoDB advises keeping the connection pool larger than the number of active
change streams to avoid notification latency; applications therefore reserve at
least one connection beyond ordinary workload demand per active manager. See
[MongoDB change-stream performance considerations](https://www.mongodb.com/docs/manual/changeStreams/).

## High-Level Design

```text
application
    |
    v
cached database / collection facade
    |-- session or incompatible read --> PyMongo, no cache
    |
    +-- eligible read --> manager checks HEALTHY
                              |              |
                         cache hit       PyMongo primary+majority read
                              |              |
                              +-------> race-safe admission
                                             |
                                      BSON weighted LRU

database change stream --> supervisor --> event router
                                         |-- evict document aliases
                                         +-- advance result generation
```

The async supervisor uses one task associated with its event loop; the sync
supervisor uses a managed worker and synchronization primitives. Neither exposes
the worker as part of the public API.

## Low-Level Design

Cache keys include namespace generation, operation kind, a canonical BSON
representation of the complete supported request, and the configured result
limits. Identity keys additionally contain the declared key fields and exact
values. A document record stores its BSON payload, byte weight, identity aliases,
and recency position. A derived record stores its BSON payload, byte weight,
database-result generation, and recency position.

The event router updates state in this order under the manager lock: establish
the event's namespace, evict the affected document aliases when a document key
exists, advance the derived-result generation, and record the latest usable
resume token only after successful handling. A failed handler clears its
affected scope and transitions to recovery rather than leaving a partly applied
event.

Read admission captures generations before I/O, then repeats generation checks
under the lock. It stores encoded payloads only after the checks pass. Query and
aggregation cursors stage their values outside the cache; only complete results
within the entry cap enter the store. The staging allocation is controlled by
the caller's result and cursor choices, so documentation must distinguish it
from the retained cache budget.

## Handling Retries and Errors

PyMongo retains its ordinary operation retry behavior. The cache layer does not
retry application reads or writes merely because caching was unavailable; it
either returns a cache hit or delegates one operation to PyMongo. Stream opening
and iteration failures are classified as follows:

| Failure | Cache action |
| --- | --- |
| Authorization, invalid topology, invalid stream configuration at explicit startup | Surface original error; do not silently enable an incoherent cache. |
| Temporary network/server-selection/election failure | Enter `RECOVERING`, bypass cache, retry stream open with capped exponential backoff and jitter. |
| Resumable stream interruption | Reopen with the last token and identical stream configuration; return to `HEALTHY` only after success. |
| Resume token unavailable, invalidate event, or unknown event-processing failure | Clear affected scope, discard token, establish a new stream, and bypass until healthy. |
| Cache encoding, decoding, or size-limit failure | Treat as a cache miss/admission rejection, log safely, and return the already obtained MongoDB value. |

Backoff configuration has a finite initial delay, maximum delay, and jitter;
the supervisor stops retrying when the manager closes. Startup exposes the
original fatal configuration failure rather than concealing it behind a retry
loop.

## Performance Optimizations

- Prefer document aliases for `_id` and declared unique keys; they avoid query
  serialization and provide per-document eviction.
- Use database-result generations instead of scanning every cached query after
  each write; stale results become unreachable in constant time and are removed
  lazily or under memory pressure.
- Store BSON bytes once and decode only on a hit, isolating callers while
  providing exact retained-value accounting.
- Hold the manager lock only for state reads, state transitions, and cache-index
  updates; perform MongoDB I/O and BSON encoding outside it.
- Use one database stream per manager rather than one stream per collection;
  this limits held connections and naturally covers aggregation dependencies in
  that database.
- Do not cache incomplete or oversized results. This avoids retaining partial
  cursors and prevents a single aggregation from evicting an entire working
  set.

## Risks / Trade-offs

- [Every database change invalidates all derived results] → Document identities
  remain fine-grained; metrics reveal whether a workload needs a future narrower
  result policy.
- [Majority-primary reads can add latency] → They are limited to cacheable
  facade reads and prevent cache entries from outliving a rollback or secondary
  lag; sessions remain direct PyMongo operations.
- [A stream uses a connection and may fall behind during outages] → One stream
  per manager, explicit pool guidance, bounded recovery, and bypass while
  unhealthy contain the resource and freshness impact.
- [A 64 MiB cache is not universally suitable] → The default is bounded and
  visible; applications configure it from process memory and observed values.
- [BSON encode/decode adds CPU] → It guarantees caller isolation and accurate
  accounting; identity hits avoid database round trips that dominate intended
  workloads.

## Migration Plan

1. Publish the new facades and manager as the documented supported API while
   retaining the proof-of-concept API only long enough to issue a deprecation
   notice.
2. Add a migration guide mapping existing `CachedMongoClient` configuration to
   explicit database managers, collection wrappers, cache limits, and lifecycle
   calls.
3. Release initially behind a pre-1.0 compatibility policy and collect
   observability data from integration workloads.
4. Remove the deprecated PyMongo-subclass API only in a documented breaking
   release after the migration path is available.

Rollback is application-level: replace a cached facade with the original
PyMongo collection or stop the manager. Because the backend is process-local,
no shared cache state needs migration or cleanup.
