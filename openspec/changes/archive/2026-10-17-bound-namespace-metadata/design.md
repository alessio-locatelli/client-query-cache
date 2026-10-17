# Design

## Context

See [proposal.md](proposal.md) for the motivation. The cache core currently registers state lazily and retains it until manager close. Shared publication adds a fixed native slot table, while its Python publisher and worker wrappers maintain separate namespace-keyed maps. The native `OwnerIndex.set_epoch` stores the supplied epoch exactly, so a recycled slot must receive a value greater than its previous assignment.

## Goals / Non-Goals

**Goals:** Bound namespace-keyed metadata by configured namespace capacity, let observed drops release that capacity, and preserve cache correctness for captures and readers that outlive a namespace assignment.

**Non-Goals:** This change does not bound memory held by active application requests, cached values beyond their existing byte budget, database-name configuration, or MongoDB/PyMongo objects. It does not promise immediate RSS reduction after Python objects are reclaimed.

## Decisions

### Track a fixed active set and bypass overflow

`CacheCoreConfig.max_namespaces` is a positive exact integer with a default of 1,024. The shared server passes its existing `namespaces` value to the owner core and attachment configuration. A core registers a new namespace only while below its limit. At capacity, the manager records `namespace_capacity` and executes the read natively without retaining state. It does not evict a still-active namespace, because doing so would flush useful entries and require coordinating active reads and shared slots without evidence that the collection was dropped.

The alternative is LRU eviction of active namespace state. It would admit every new name, but it would turn arbitrary namespace access into cache-wide namespace churn and complicate fencing while the database may still be reading the evicted collection. The fixed active set has predictable memory use and recovers capacity when the stream proves a collection was dropped. No additional workload research is needed to choose between these policies.

### Release state on collection lifecycle events

A processed drop invalidates the namespace, removes it from the core registries, and removes its exact entries from the weighted LRU. Drop-database and stream invalidation release all tracked namespaces in the affected database; rename releases the source and clears the destination. The separate collection and unique-key metadata caches use bounded insertion-ordered maps with the same capacity. Reads do not update map order, keeping the common metadata lookup path to a lock and dictionary lookup; new or refreshed metadata moves to the newest position. Eviction only causes a later metadata refresh, so it does not affect read correctness.

Captures retain their originating state and are valid only while that state remains registered. A core-wide monotonically increasing token initializes new states and advances namespace generation, clear/create epoch, and index-metadata generation changes. Thus a namespace recreated under the same string and a new owner slot both have a token that cannot equal an old capture. Ordinary writes advance namespace generation but leave the namespace epoch unchanged; per-identity generations keep their existing scope.

### Reuse shared slots with the existing epoch field

`IndexPublisher` stores mappings and epochs only for assigned slots. It allocates unused slot numbers first, then reuses numbers returned by namespace release. Release includes the namespace epoch observed at drop; it frees a mapping only if that assignment is still current, so a concurrent reassignment of the same name cannot be released by stale cleanup. Each worker's metadata and slot maps use bounded insertion-ordered storage sized from the attachment's `namespaces` limit. Reads do not promote an entry, avoiding extra work on shared hot reads; if a hint is evicted, the worker requests fresh metadata.

The alternative is to add a separate slot-incarnation field to every shared protocol message and native-index call. That would make the distinction explicit but expand the protocol and native layout. A core-wide increasing namespace epoch already satisfies the native reader's exact epoch comparison, so a second generation field is unnecessary. The Rust implementation confirms `set_epoch` stores the supplied value; the regression tests must verify that a stale reader cannot observe a value published after slot reuse.

### Capacity and failure behavior

Capacity exhaustion is a cache bypass, never a read error. Shared metadata requests for untracked names do not allocate owner epoch records or native slots. Worker-side eviction only removes local lookup hints; the worker can request fresh metadata again. Owner incarnation remains the fence after restart.

## Risks / Trade-offs

- **A tracked namespace can occupy capacity for its lifetime** → A processed drop, drop-database event, stream invalidation or manager close releases it. Names beyond capacity bypass safely until capacity becomes available.
- **Python may retain freed arenas in RSS** → Validation measures retained namespace-map cardinalities and traced Python allocations over repeated churn; the contract bounds reachable metadata rather than guaranteeing RSS falls immediately.
- **Frequent churn can cause repeated metadata probes and cache misses** → This is limited to names that exceed configured simultaneous capacity or whose local metadata was evicted; MongoDB reads remain authoritative.

## Migration Plan

No persistent data or external protocol survives owner restart. Existing `SharedCacheConfig.namespaces` remains the shared slot limit and now also bounds owner and worker namespace metadata. Process-local callers receive the default 1,024 namespace limit and may set `CacheCoreConfig.max_namespaces`. Exhaustion bypasses without changing returned MongoDB results.

## Open Questions

None. The capacity, bypass and drop-reclamation behavior are specified in the two delta specs.
