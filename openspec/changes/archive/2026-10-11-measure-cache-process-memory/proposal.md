# Proposal

## Why

`shared_budget_bytes` and `max_entry_bytes` bound stored and captured BSON, not process memory. The public guides already say so, but they give operators no measured amplification to size containers with, and nobody has checked whether part of the gap is avoidable. Fresh-process measurements of cached versus direct PyMongo reads now show the gap ranges from about 1.1 times the stored BSON for large results to about 90 times for tiny results with large filters, and that two pieces of per-entry bookkeeping are pure duplication.

## What Changes

- Add a reproducible research harness that compares cache-enabled and direct PyMongo reads in fresh, disposable containers and records process RSS, USS, PSS, per-phase peak RSS, and container cgroup memory alongside cache counters.
- Stop allocating an alias collection for every cached identity and stop retaining a separate namespace identifier in every cache entry and key.
- Record the measurements, their limits, and the classification of each observed cost in a repository report.
- Extend public capacity guidance with measured memory beyond the BSON budget, practical sizing considerations, and the expected retention of freed memory after eviction, cursor closure, and manager shutdown; align `context7.json`.
- No new configuration, budget semantics, RSS-based eviction, memory monitor, or CI benchmark.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cache-core`: Resident bookkeeping must not duplicate namespace identifiers per entry or allocate alias storage for identities without aliases.
- `public-library-documentation`: Capacity guidance must quantify process memory beyond the BSON budget and explain how to size for it.

## Impact

- Code: `src/client_query_cache/_core/manager.py` and `_core/namespace.py`; regression tests under `tests/core/`.
- Research and evidence: `research/process_memory/measure.py`, `reports/process-memory/summary.md`, and a link from the development index.
- Public documentation: `docs/user/operations/deployment.md`, `docs/user/reference/api.md`, and `context7.json`.
- [Issue #245](https://github.com/alessio-locatelli/client-query-cache/issues/245) tracks the remaining avoidable key-tree overhead, which needs a separate canonical-key design change.
