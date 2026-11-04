# Design

## Context

`CacheCoreConfig` and `CacheSnapshot` expose the process-local BSON budget as `shared_budget_bytes`, while `SharedCacheConfig` uses `budget_bytes` for its cross-process capacity. The name also needs explanatory prose in the API reference and the deployment guide.

## Decisions

### D1. Rename directly, without an alias

This is a direct pre-1.0 rename. A compatibility alias would add ambiguous constructor precedence and a second snapshot name without a demonstrated consumer need, and keeping the name would preserve the misleading cross-process reading. The policy deliberately requires consumer source updates; it makes no claim that external consumers do not exist. The permanent specification states only the supported name; a test verifies that the old name is rejected and the release notes announce it, so no requirement preserves the migration.

### D2. Update every maintained consumer, keep historical identifiers

Update `shared.py`, the coordinator's core construction and its group-observation `cache` mapping together with their readers and tests; all cooperating processes use one installed version, so this is a same-version observation-field update rather than a protocol change. Update maintained executable research and benchmark code that constructs current configuration. Preserve versioned report formats, historical reports and archived OpenSpec artifacts: the version-1 stream-cost report keeps its serialized `measurement.logical_metrics.cache.shared_budget_bytes` field, populated from `CacheSnapshot.budget_bytes`, so its schema and reports stay valid. Migration guidance belongs to the release notes; current API guidance uses only current names.
