# Shared-cache implementation reference

Public configuration and operations belong in the [shared API reference](../user/reference/shared-cache.md) and [deployment guide](../user/operations/shared-cache.md). This page records details needed when changing the native implementation or investigating memory and publication costs.

## Ownership and validity

The parent starts a spawned owner with its own MongoDB client. Workers attach read-only native value mappings and bounded admission queues. The Python cache core remains authoritative for admission, eviction and invalidation; Rust supplies the shared index, payload storage and queue machinery. Process-local `CacheManager` does not use this shared storage path.

Native readers check owner incarnation, namespace generation, database availability and upstream progress before serving a hit. Local misses capture validity tokens before reading MongoDB. The owner starts authoritative core capture before validating those tokens; reversing that order leaves a write race. Restart replaces mappings and workers discard cached attachment metadata. Preserve the lock-order and publication fences when changing this path.

The [delivery design](../../openspec/changes/archive/2026-10-15-ship-shared-worker-cache/design.md) and [miss-path design](../../openspec/changes/archive/2026-10-17-reduce-shared-cache-miss-cost/design.md) record the mechanisms and invariants. The [manager decision](decisions/keep-explicit-cache-managers.md) explains the public API boundary. Prototype cursor support in research adapters is not part of the public shared manager's cached-read scope.

Research adapters publish fully consumed positive-limit find results under their exact query discriminator. Local exact hits reuse identity-reader validity checks; misses and compatible larger-limit hits retain owner selection and authoritative capture. Publication uses the namespace's metadata epoch, while writes remove every published find result in that namespace without removing unrelated identity results. This includes writes whose identity cannot be canonicalized. Unbounded finds remain owner-served. The [sorted-find investigation](../../reports/shared-worker-cache/sorted-find/results.md) defines the measurement and public-promotion boundary; public cursor delivery is tracked by [#295](https://github.com/alessio-locatelli/client-query-cache/issues/295).

## Native capacity limits

`SharedCacheConfig` validates native layout bounds before starting the owner:

- `arena_bytes <= ((1 << 32) - 1) * 8`, or 34,359,738,360 bytes, because arena word offsets use 32 bits.
- `namespaces <= (1 << 32) - 1`, or 4,294,967,295 slots.
- `slots` is a power of two no greater than `1 << ((sys.maxsize // 64).bit_length() - 1)`, so index sizing fits the native signed address space.
- `connections >= 2`, and `max_entry_bytes` must fit both `budget_bytes` and `arena_bytes`.

These are representational bounds, not recommended allocations or a claim that an allocation near them is feasible on a host. Public guides explain capacity pressure through hit rates and memory measurements rather than these layout numbers.

## Memory outside the accounted budget

The default 65,536-slot index occupies about 4 MiB in addition to the payload arena. Each attached worker maps shared pages and owns a bounded admission queue; Python/PyMongo objects, decoded documents and transient transport frames add private memory. Summing worker RSS double-counts shared pages: use group PSS or container memory alongside owner and worker measurements.

Workers retain up to 8,192 key encodings. The owner retains up to 1,024 decoded read-shape keys and 256 encoded read-shape keys. These key caches retain only keys encoded in at most 4 KiB; canonical Python objects add overhead. Larger keys remain usable but are not retained in those encoding caches. Core state, publisher assignments and worker namespace hints are bounded by the configured `namespaces` capacity. A processed collection drop releases the owner's state and shared slot; reads for other names bypass shared caching while capacity is exhausted.

## Profile attribution for the public release workload

A separate one-repetition cProfile run for the [0.8.0 public measurements](../user/benchmarks/shared-cache.md) traced 8,000 shared hot reads per execution model. Instrumented time summed to 484 ms sync and 497 ms async. Cumulative times overlap and must not be added:

| Operation                                      | Sync cumulative ms | Async cumulative ms |
| ---------------------------------------------- | -----------------: | ------------------: |
| Identity normalization and key preparation     |              110.0 |               109.9 |
| Local index selection, payload copy and decode |               61.1 |                60.8 |
| Namespace getter, 32,000 calls                 |                3.8 |                 3.8 |

Identity preparation accounted for about 22–23% of profile time and local selection about 12–13%. No key encoding or namespace construction occurred during measured hot reads: key encodings are reused and collection views retain their namespace. Profiling overhead makes this run unsuitable for latency comparisons.

Use `--repetitions 1 --profile-dir /tmp/agents/shared-cache-profiles` with the public benchmark runner and a separate output file. Inspect `.pstats` files for one model, workload and path with Python's [pstats tooling](https://docs.python.org/3.14/library/profile.html#the-stats-class). Keep raw outputs untracked.
