# Proposal

## Why

The process-local cache retains Python query trees, entries, and generation bookkeeping outside its BSON budget; the historical [process-memory study](../../../reports/process-memory/summary.md) identifies substantial overhead for small results and long keys. Moving that ownership boundary into the library's Rust implementation can reduce repeated bookkeeping, with current complete-read and resource measurements determining whether the change is retained.

## What Changes

- Integrate native process-local storage and invalidation into the library and compare it through the existing synchronous and asyncio read APIs.
- Add a reproducible evaluation with correctness, performance, and resource gates defined in the delta spec. Stable proven improvements qualify without a minimum percentage; material adverse trade-offs require a documented decision.
- Retain a qualifying native implementation as the ordinary process-local core in this branch and PR; remove an unqualified candidate while preserving reproducible evidence.

Implementation, evaluation, and qualified production integration form one change. A successful evaluation must continue through default-build integration without a follow-up ticket or PR. Shared-cache protocol/ownership rewrites, change-stream transport/recovery rewrites, cursor capture/serialization rewrites, selective invalidation, public budget renaming, and new metadata limits are outside scope.

## Capabilities

### New Capabilities

- `process-local-cache-evaluation`: Controlled native-core comparison, conformance and resource gates, and same-change retention of a qualifying process-local implementation.

### Modified Capabilities

None. Existing cache and read requirements remain the public contract regardless of the core's implementation language.

## Impact

The implementation targets the existing native crate, the library's core integration, focused conformance tests, and the existing benchmark/memory harnesses. A retained implementation changes ordinary process-local storage internally while preserving public construction, configuration, codecs, results, and consistency behavior. The final implementation's architecture guide and affected public guides/Context7 rules are updated in this change.

This is new work after the completed [shared-cache investigation #341](https://github.com/alessio-locatelli/client-query-cache/issues/341). The independent [metadata-bounds contract #337](https://github.com/alessio-locatelli/client-query-cache/issues/337) remains separate; lower measured memory consumption would not establish an RSS ceiling or complete that issue.
