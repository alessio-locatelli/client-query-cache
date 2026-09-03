## Why

MongoDB change streams provide a supported source of majority-committed change
events, but the current proof of concept does not turn them into a safe client
cache. It is synchronous only, keeps unbounded query results, and has no
recovery path for a disconnected or unresumable stream. This change defines a
maintainable public foundation for a process-local PyMongo cache whose value is
event-driven coherency rather than time-to-live expiration.

## What Changes

- Establish a public, composition-based cached database and collection API for
  synchronous and native asyncio PyMongo clients on CPython 3.13 and later.
- Support bounded document, unique-lookup, materialized query, and aggregation
  result caching. Use document-level eviction where identity is known and
  database-generation invalidation where result membership is not knowable.
- Add a database-scoped change-stream supervisor with explicit lifecycle,
  resumable recovery, clear-on-uncertainty, and cache-bypass behavior while the
  stream is unhealthy.
- Make cacheable reads use primary read preference and majority read concern;
  bypass session-bound and incompatible read operations rather than weakening
  their MongoDB semantics.
- Define a bounded in-memory BSON LRU backend, operational health signals, and
  the documentation, packaging, CI, test, and release plan needed to publish a
  reliable library.
- Retire the proof-of-concept assumption that arbitrary PyMongo methods are
  transparently cacheable. Unsupported operations will delegate directly to
  PyMongo or be explicitly documented as out of scope.

## Capabilities

### New Capabilities

- `cached-read-api`: Provides explicit synchronous and asyncio cached database
  and collection facades with a defined read eligibility contract.
- `change-stream-coherency`: Maintains document and derived-result cache
  coherency from database-scoped MongoDB change streams.
- `bounded-memory-cache`: Stores cache entries in a process-local, byte-bounded
  BSON LRU backend without exposing mutable cached values.
- `cache-lifecycle-observability`: Exposes startup, health, recovery, and
  capacity state so applications can operate the cache safely.

### Modified Capabilities

- None. The repository has no existing OpenSpec capability specifications.

## Impact

- Affected package areas: the current synchronous PyMongo subclasses and their
  cache, cursor, command, and change-stream modules will be replaced or
  reorganized behind composition-based facades; an asyncio adapter will be
  added.
- Affected public API: the experimental `CachedMongoClient` configuration model
  will not define the stable interface. The change introduces explicit cache
  manager lifecycle and collection/database wrapping.
- Affected dependencies and tooling: the project will pin a supported PyMongo
  range that includes the generally available asyncio API, define a Python 3.13+
  CI matrix, and add integration coverage against a replica-set MongoDB
  deployment.
- Affected operations: applications need `find` and `changeStream` privileges
  on cached namespaces and must budget one change-stream connection per cached
  database manager.
