# Design

## Context

See [proposal.md](proposal.md#why) for motivation and [the delta specs](specs/) for the required behavior.

Existing evidence covers allocations, not process memory: the [Memray churn tier](../../../docs/development/memory-regression-tests.md) bounds peak live allocations of a synthetic core, the [cursor report](../../../reports/cached-read-cursors/summary.md) records `tracemalloc` heap peaks and capture bounds, the [filter normalization report](../../../reports/query-filter-normalization/summary.md) records transient key heap, and the [shared worker cache study](../../../docs/development/research/shared-worker-cache-feasibility.md) records group PSS for 4 KiB `_id` reads. None compares cache-enabled and direct PyMongo process memory for different entry shapes, measures memory left after eviction, cursor closure, or manager closure, or separates container memory from process RSS.

Exploratory `tracemalloc` attribution of resident entries found per-entry bookkeeping that is identical across entries:

- Every `IdentityState` allocates an empty `set` for `alias_keys` (216 bytes on CPython 3.14), although only identities resolved through a unique index ever receive an alias.
- Every read builds a fresh `NamespaceId` through the facade's `_namespace()`, and admission stores that object in the entry and its key (72 bytes per entry), although `NamespaceState.namespace` already holds an equal registered instance.
- Canonical keys wrap each order-sensitive node in an extra generic-sequence layer, roughly doubling the tuples of a filter key (about 320 of 650 bytes for a one-predicate `find_one` key).

## Goals / Non-Goals

**Goals:**

- Fresh-process measurements that a maintainer can rerun with one command, without tracking raw output.
- Remove the first two duplications without changing key equality, alias semantics, or budget accounting.

**Non-Goals:**

- Changing the canonical key representation; see decision 6.
- Charging bookkeeping to the BSON budget or bounding entry counts; see decision 7.
- Returning freed memory to the operating system.

## Decisions

### 1. One disposable container per measured process

The harness (`research/process_memory/measure.py`) starts the repository's disposable `mongo:8.0.4-noble` replica set through the existing `research/collection_adapter/live_error.py` fixture, seeds it, and runs every measured cell as a fresh Python process in its own container. The container reuses the `mongo:8.0.4-noble` image only for its Ubuntu user space; no `mongod` runs there. It mounts the checkout, its virtual environment, and the interpreter read-only, disables SELinux relabeling instead of relabeling the checkout, and uses host networking to reach the mapped server port. MongoDB memory and other containers therefore never enter the measured cgroup.

| Alternative                              | Pros                                     | Cons                                                                                  |
| ---------------------------------------- | ---------------------------------------- | ------------------------------------------------------------------------------------- |
| Container per process (chosen)           | Own cgroup counters; no cross-cell state | About one second of startup per cell; image's glibc differs from Fedora hosts         |
| One container running every cell         | Faster                                   | Cgroup peak and page cache shared across cells                                        |
| `systemd-run --user --scope` per process | No image                                 | Needs the host user manager, differs between Toolbx, Distrobox, and CI                |
| `tracemalloc` or Memray only             | Already used                             | Measures allocations, not RSS, USS, PSS, or cgroup memory; duplicates existing suites |
| Dedicated slim runtime image             | Clearer intent                           | Another image to pull and pin                                                         |

Unknowns: allocator behavior under musl or jemalloc images is not measured. Conclusion: no further research is required; the report states the glibc version.

### 2. Metrics and phase boundaries

Each checkpoint runs `gc.collect()`, then records `VmHWM` from `/proc/self/status`, `psutil` RSS, USS, and PSS, cgroup `memory.current`, `memory.peak`, and the `anon`/`file` lines of `memory.stat`, cache snapshot counters, and the GC-tracked object count. Writing `5` to `/proc/self/clear_refs` then resets `VmHWM`, so each phase reports a true kernel high-watermark rather than a sampled peak. The container mounts its cgroup read-only, so `memory.peak` is a per-process lifetime peak. After the scenario, `close` measures without the manager; `trimmed` calls glibc `malloc_trim(0)` only to separate reusable allocator memory from live memory. Direct cells run identical reads with the same checkpoints, so the cached-minus-direct difference excludes driver, interpreter, and application-retained results.

A sampling thread was rejected: it misses short spikes and adds observer allocations. `tracemalloc` is used only for exploratory attribution and is never reported as RSS.

### 3. Workloads

All cells use the default 1 MiB maximum entry size, and synchronous and asyncio cells share one scenario implementation through an await-if-awaitable helper.

- `documents`: `find_one` by `_id` of 4.4 KB catalogue documents into the default 64 MiB budget, then a warm pass and an eviction pass.
- `result-sets`: sorted `find` results of 224 such documents (about 0.93 MiB each) into 64 MiB, plus phases where the application retains and releases 16 results.
- `small-entries` and `large-keys`: generic `find_one` with 59-byte results into a 4 MiB budget, with a one-predicate filter or a 48-value `$in` filter built per request, as applications build filters from requests.
- `partial-cursors`: 32 open find cursors that each consume 220 of 224 documents, near the capture limit, then close.
- `cycles`: five rounds of opening a manager, reading 40,000 small results into a 1 MiB budget with eviction, and closing it, to separate leaks from allocator retention.

Smaller budgets keep the small-entry scenarios to about a minute per cell while still filling and evicting.

### 4. Harness location

`research/` holds exploratory programs outside the coverage gate and CI, as `reduce-shared-cache-overhead` already records. A `benchmarks/` package would require unit tests and coverage for code with no production role, and `tests/benchmark/` runs in every `just tests_and_coverage`. Conclusion: no permanent benchmark is warranted.

### 5. Removing the duplications

`IdentityState.alias_keys` becomes an immutable `frozenset` defaulting to the shared empty `frozenset()`. Publication, displacement, write invalidation, and reclamation replace it instead of mutating it. An identity has at most one alias per qualifying unique index, so copy-on-write costs are negligible.

| Alternative                                     | Pros                          | Cons                                                         |
| ----------------------------------------------- | ----------------------------- | ------------------------------------------------------------ |
| Shared empty `frozenset`, copy-on-write         | No `None` branches; tiny diff | Replacement allocates a new set per alias change             |
| `set \| None`, created on first alias           | Mutation stays in place       | Every reader and mutator needs a `None` branch               |
| Per-namespace reverse map of aliased identities | No field in `IdentityState`   | Second structure to keep consistent under the namespace lock |

Captures take the namespace from the registered `NamespaceState`, so every entry and key admitted from them references one instance. Caching a `NamespaceId` in each `CachedCollection` would also save the per-read construction, but views are created per `get_cached_collection()` call and per attribute access, so it would not deduplicate resident entries. Conclusion: neither alternative needs follow-up.

### 6. Canonical key layering is deferred

Making `canonicalize()` keep order-sensitive tags while canonicalizing only their payload would remove about half of the tuples of a filter key and also reduce key CPU. It changes the canonical representation of every namespace key and the equality reasoning in `canonical.py`, `order_sensitive_keys.py`, and find-family hashing, so it needs its own differential and property tests. Unknown: the CPU gain on hits. [Issue #245](https://github.com/alessio-locatelli/client-query-cache/issues/245) tracks it.

### 7. Budget semantics stay BSON-only

Charging an estimated per-entry overhead or capping entry counts would bound small-entry memory, but it would change what `used_bytes` and `shared_budget_bytes` mean, require a new estimate per Python version, and break existing capacity reasoning. The public guidance instead shows how memory scales with entry and filter size and recommends a lower budget for small-result workloads. Conclusion: no follow-up unless users report the documented guidance to be insufficient.

## Risks / Trade-offs

- [Figures depend on CPython, PyMongo, glibc, and document shape] → Public guidance names versions and conditions and presents ratios as examples, not guarantees.
- [Copy-on-write alias storage regresses alias behavior] → Existing alias tests, new reassignment tests, and the Memray `identity-with-alias` churn case cover publication, displacement, writes, and pruning.
- [Sharing the registered namespace keeps the first caller's `NamespaceId` alive] → It lives exactly as long as its `NamespaceState`, which already persists until close.
