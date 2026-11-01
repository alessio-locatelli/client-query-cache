# Proposal

## Why

The remaining Python internals allocate and traverse data around the Rust cache engines, and the shared owner still maintains Python residency and publication metadata. Replacing justified portions can reduce complete-operation CPU or memory costs while preserving the public API.

## What Changes

- Assess all remaining internal responsibilities and migrate the useful portions directly into ordinary library execution, with a user-facing performance changelog entry for retained improvements.
- Keep independently measurable portions in one branch and PR; a successful measurement completes that portion rather than starting a separate integration project.
- Introduce short end-to-end development checks before expensive confirmation campaigns.

The component assessment, evidence boundaries, proposed architecture, and concrete reasons that could require a split belong to [design.md](design.md). Acceptance obligations belong to the delta specs; executable work belongs to [tasks.md](tasks.md).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `process-local-cache-evaluation`: Stage remaining native hot-path replacements through fast integrated checks and independently attributable decisions.
- `shared-cache-benchmarking`: Qualify shared-owner rewrites using drained admission work and current scoped evidence, completing successful integration within the same change.

## Impact

The affected areas are `src/client_query_cache/_core/`, `_shared/`, the sync/async integration points, and the existing `native/shared-index` extension. Benchmark collectors, regression cases, the performance report, and `CHANGELOG.md` accompany retained changes. No new public configuration, serializer dependency, or platform requirement is proposed. Existing active native-coverage and worker-fault studies remain separate.
