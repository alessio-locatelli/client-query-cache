# Proposal

## Why

Cache-eligible reads rebuild a discriminator during bypass classification, lookup, and admission. [Issue #248](https://github.com/alessio-locatelli/client-query-cache/issues/248) identifies avoidable CPU work on hits and misses that remains after compact key nodes were introduced.

## What Changes

- Establish one canonical discriminator preparation per read execution, with reuse through cache lookup and admission.
- Preserve native execution, cache eligibility, bypass classification, and cache outcomes.
- Measure the CPU effect against the current compact-key implementation.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cache-core`: bound discriminator preparation work and preserve bypass precedence when preparation fails.

## Impact

The implementation touches shared read classification, find shapes, and synchronous and asyncio collection/cursor facades. Regression coverage belongs in existing core, cursor, collection, and observability tests; performance evidence belongs alongside the cursor benchmarks. There are no public API, dependency, storage-format, or deployment changes. The implementation decisions and affected method boundary are in [design.md](design.md).
