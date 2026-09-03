## 1. Establish the supported project surface

- [ ] 1.1 Replace the proof-of-concept README with an audience, prerequisites, installation, synchronous and asyncio quick-start, lifecycle, consistency, capacity, recovery, security, and non-goals guide; verify every command and code sample against the implemented public API.
- [ ] 1.2 Add durable architecture and operations documentation derived from `design.md`, including system requirements, capacity-sizing formula, HLD/LLD diagrams, retry/error behavior, connection-pool guidance, and performance trade-offs; verify internal links and external MongoDB references resolve.
- [ ] 1.3 Define the public API reference and migration guide from experimental `CachedMongoClient` subclasses to composed managers and facades; verify the guide covers limits, lifecycle calls, unique-key declarations, and rollback to raw PyMongo collections.
- [ ] 1.4 Update package metadata for a public CPython 3.13+ typed distribution with `pymongo>=4.13,<5`, a complete project description, classifiers, license and repository links, and explicit development dependencies; verify a clean wheel and source distribution build and install.

## 2. Create shared cache primitives

- [ ] 2.1 Replace the unbounded prototype cache types with a driver-neutral cache manager contract, lifecycle states, inspection snapshot, error types, request canonicalization, and unique-key declaration model; verify focused unit tests cover valid and rejected cacheable requests.
- [ ] 2.2 Implement the shared 64 MiB default, 1 MiB maximum-entry weighted BSON LRU store with configurable limits, namespace clearing, alias removal, and accurate byte accounting; verify unit tests cover LRU eviction, oversize rejection, shared budgets, and caller-value isolation.
- [ ] 2.3 Implement document identity and derived-result records with namespace and generation guards; verify a deterministic concurrency test proves an invalidation cannot admit an older in-flight result.
- [ ] 2.4 Implement cache statistics and safe structured lifecycle logging without document or credential values; verify snapshot counters and log records in unit tests.

## 3. Implement database change-stream coherency

- [ ] 3.1 Implement a database-scoped stream configuration and event router for insert, update, replace, delete, drop, rename, and invalidation events; verify event fixtures evict document aliases and invalidate derived results as specified.
- [ ] 3.2 Implement synchronous manager startup, shutdown, and a managed stream worker with primary failure propagation, recoverable state, capped exponential backoff with jitter, and direct-to-MongoDB bypass while unhealthy; verify deterministic tests for startup failure, recovery, and close.
- [ ] 3.3 Implement asyncio manager startup, shutdown, and an event-loop-bound stream task with behavior equivalent to the synchronous manager; verify lifecycle and cancellation tests do not leak tasks or connections.
- [ ] 3.4 Implement resume-token handling with identical stream configuration, clear-on-unresumable continuity loss, and post-invalidation re-establishment; verify controlled cursor failures cover resumable recovery, token-loss clearing, and no cache hits during recovery.

## 4. Implement supported PyMongo facades

- [ ] 4.1 Implement composed synchronous cached database and collection facades that bind eligible reads to primary read preference and majority read concern, retain raw-PyMongo fallback for unsupported operations, and bypass all session-bound reads; verify a spy client observes the intended routing and bypass behavior.
- [ ] 4.2 Implement synchronous identity lookup caching for `_id` and declared simple or compound unique keys, including alias eviction after an external write; verify integration tests use a second raw PyMongo client to perform inserts, updates, replacements, and deletes.
- [ ] 4.3 Implement synchronous fully materialized `find`, `aggregate`, `count_documents`, `estimated_document_count`, and `distinct` caching, with no admission for partial, tailable, exhaust, or oversize cursor results; verify integration tests cover cache hits and database-generation invalidation for membership, sorting, limit, projection, and aggregation changes.
- [ ] 4.4 Implement native asyncio database and collection facades with the same supported reads, identity behavior, cursor-completion rules, and cache bypass semantics; verify parity integration tests against PyMongo `AsyncMongoClient`.
- [ ] 4.5 Define and test ownership, close, and exception behavior for facades and managers so the library never closes a caller-owned PyMongo client unless the public API explicitly created it; verify repeated close and context-manager tests in both execution models.

## 5. Build a representative integration and fault test environment

- [ ] 5.1 Replace the proof-of-concept test setup with isolated replica-set fixtures that wait for primary election and expose independent raw writer clients; verify the suite fails clearly when its MongoDB prerequisite is unavailable.
- [ ] 5.2 Add end-to-end sync and asyncio tests for a warm-cache external write, collection drop, rename, resume after a transient stream error, and clear-and-reopen after lost resume history; verify every test asserts both returned data and manager health/counter state.
- [ ] 5.3 Add property and boundary tests for BSON key canonicalization, aliases, LRU capacity, projections, cursor materialization, cache admission races, and errors that must not leave stale entries; verify they run deterministically without a live database where possible.
- [ ] 5.4 Add an opt-in benchmark suite that measures raw versus warm document and derived-result reads, invalidation cost, BSON encode/decode overhead, and memory-budget behavior; verify it reports measurements without making an unsupported performance guarantee in project documentation.

## 6. Add quality gates and release automation

- [ ] 6.1 Configure formatting, linting, type checking, unit tests, integration tests, coverage reporting, package build, and documentation-link checking for the CPython 3.13+ support policy; verify each command has a documented local equivalent and fails independently on a seeded defect.
- [ ] 6.2 Add GitHub Actions workflows for fast pull-request checks and replica-set integration coverage, with dependency caching that does not cache credentials; verify workflow YAML with its local validator and inspect the rendered job matrix.
- [ ] 6.3 Add release checks for a clean build, wheel installation in an isolated environment, import of sync and asyncio public APIs, and version/tag consistency; verify the release job is non-publishing until publishing credentials and ownership are deliberately configured.
- [ ] 6.4 Run the complete quality gate, review the resulting public API and docs for unsupported claims, run `openspec validate bootstrap-client-cache-foundation --strict`, and record the exact verification results before marking this change complete.
