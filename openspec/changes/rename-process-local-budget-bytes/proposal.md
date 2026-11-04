# Proposal

## Why

The process-local budget bounds stored BSON across one manager's collections, yet `shared_budget_bytes` suggests that values are shared between processes. `SharedCacheConfig` already names its cross-process capacity `budget_bytes`, so the process-local name is both misleading and inconsistent.

## What Changes

- **BREAKING**: Rename `CacheCoreConfig.shared_budget_bytes` and `CacheSnapshot.shared_budget_bytes` to `budget_bytes` without a compatibility alias, including validation messages, the shared coordinator's observation mapping and maintained usage references.
- Keep the serialized version-1 stream-cost report field independent of the Python name.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cache-core`: Name the process-local BSON budget `budget_bytes` in the existing budget and inspection requirements.

## Impact

Public configuration and snapshot interfaces, the shared coordinator's group-observation mapping, maintained benchmarks, research code, tests and documentation change names only; behavior, validation rules and capacity accounting are unchanged. Historical reports and archived OpenSpec artifacts keep their original identifiers.
