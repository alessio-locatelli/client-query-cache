## Context

See proposal.md for motivation and specs/cached-read-api/spec.md for the required surface.

Audit result for the 0.3.0 public members, identical in the synchronous and asyncio variants:

| Member                                                                                                              | Documented in `docs/user/reference/api.md` | Production caller                       | Outcome      |
| ------------------------------------------------------------------------------------------------------------------- | ------------------------------------------ | --------------------------------------- | ------------ |
| `CacheManager.client`, `cache_core`, `close`, `__enter__`/`__exit__`                                                | yes                                        | yes                                     | keep         |
| `CacheManager.snapshot`, `stream_health_snapshot`, `stream_cost_snapshot`, `active_stream_cost_databases`           | yes (Diagnostics)                          | users, `otel`                           | keep         |
| `CacheManager.cached`                                                                                               | yes                                        | users                                   | rename       |
| `CacheManager.ensure_cache_eligible`                                                                                | no                                         | none (only `test_public_observability`) | delete       |
| `CacheManager.cache_ineligibility_reason`, `default_collation_for`, `unique_keys_for`                               | no                                         | `CachedCollection` and cursors only     | make private |
| `CachedDatabase.manager`/`name`/`raw`; `CachedCollection.database`/`name`/`raw` and the six PyMongo-mirroring reads | yes                                        | yes                                     | keep         |

`CachedCollection` and `CachedCursor` already call the sibling-private `_cache_ineligibility_reason` across classes, so underscore-prefixed members used across the package's own classes follow existing practice.

## Goals / Non-Goals

**Goals:**

- Every public member of the manager and cached views is either in the public guides or private.
- The accessor's name states that it returns a cached collection.

**Non-Goals:**

- `CacheCore`, `ChangeStreamCoordinator`, and `DatabaseStreamSupervisor` stay as they are. The API guide already presents them as advanced exports, the stream-cost benchmarks construct them directly, and `otel` accepts `cache_core=`. Un-exporting or privatizing their methods is a separate compatibility decision that this change does not make, and it needs no follow-up task here.
- No deprecation alias for removed or renamed names (see Decision 1).

## Decisions

### 1. Accessor name: `get_cached_collection`, no alias

| Option                              | Pros                                                                                                                                         | Cons                                                                                                                                                     |
| ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cached` (status quo)               | Short.                                                                                                                                       | Reads as a predicate returning `bool`; says nothing about the returned object.                                                                           |
| `cached_collection`                 | Noun phrase; matches the variable name used throughout the guides.                                                                           | Reads like a property, and `cached_collection = manager.cached_collection(c)` repeats itself.                                                            |
| `get_cached_collection` (chosen)    | Verb phrase that states the return type; follows PyMongo's own `MongoClient.get_database` and `Database.get_collection` accessor convention. | Longest of the three.                                                                                                                                    |
| Keep `cached` as a deprecated alias | Eases migration.                                                                                                                             | Keeps the misleading name discoverable. The project is pre-1.0 and 0.2.0 already shipped a breaking `cached` change, so a clean break matches precedent. |

Unknowns: none. Follow-up: none.

### 2. `ensure_cache_eligible` is deleted, not made private

Nothing but one test calls it; `cache_ineligibility_reason` answers the same question and more. AGENTS.md requires deleting unused production code. This supersedes the archived `2026-10-02-improve-public-cache-observability` design, which kept the boolean method public "where advanced callers rely on it". No documented caller exists. Alternatives: keep it public and document it (rejected: it duplicates `BypassReason` information that snapshots already surface, and users have no way to supply the probe callable it requires), or make it private (rejected: dead code).

Unknowns: whether any external user calls it. That cannot be established during planning, and the method's required probe argument, which holds internal metadata types, makes external use implausible. Follow-up: none.

### 3. The three wiring methods become underscore-prefixed

`cache_ineligibility_reason`, `default_collation_for`, and `unique_keys_for` become `_cache_ineligibility_reason`, `_default_collation_for`, and `_unique_keys_for`. Alternatives: move the logic into a helper object shared by manager and view (rejected: a larger refactor with no user-visible gain), or pass the manager's metadata caches to `CachedCollection` directly (rejected for the same reason).

Unknowns: none. Follow-up: none.

### 4. `close` stays public

The request suggested making `close` private to push users toward `with`. Rejected: the documented recommendation is one long-lived manager per client per process, whose lifetime may not fit a single `with` block (for example, startup and shutdown hooks of an application framework), and the request itself lists `close` as self-documenting. The `close` docs already tell users to close the manager whenever they close its client. The context-manager form stays documented as the preferred form.

Unknowns: none. Follow-up: none.

### 5. A surface test guards the result

One parametrized test per variant compares each class's public attribute names with the documented set. Alternative: rely on review (rejected: the leak happened precisely because nothing prompted it). Comparing the set to the guide's text automatically (rejected: duplicates tooling for little value and the guide is prose).

## Risks / Trade-offs

- [0.3.0 users calling `cached` or the removed members break at upgrade] → Mark all three as **Breaking** in `CHANGELOG.md`; the rename is a mechanical find-and-replace.
- [The in-flight `add-real-usage-examples` change cites `cached(`] → tasks.md updates its planning artifacts and examples so it archives against the new name.
- [A future public member is added without documentation] → The surface test fails until the set and the guide are updated together.
