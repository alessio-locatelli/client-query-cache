# Proposal

## Why

[Issue #258](https://github.com/alessio-locatelli/client-query-cache/issues/258) identifies client CPU overhead on cache-miss `find` reads under collection-wide invalidation. Reducing that cost improves workloads whose write rate prevents useful cache hits.

## What Changes

- Remove redundant preparation and snapshot work from cursor executions.
- Extend the existing invalidation research harness with isolated miss and warm-hit measurements, and record the evidence in its research report.

## Capabilities

No requirements change. This refactor preserves the existing `cache-core` and `cached-read-api` contracts; `.openspec.yaml` declares `skip_specs: true`.

## Impact

Internal find-key preparation, synchronous and asyncio cursors, cursor capture, and the shared-worker capture adapter. No public API or dependency changes.
