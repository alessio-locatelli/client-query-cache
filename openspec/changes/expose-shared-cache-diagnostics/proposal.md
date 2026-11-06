# Proposal

## Why

An operator whose shared-cache hit rate is low cannot tell from the public API why: `SharedCacheManager.snapshot()` reports three worker-local totals, so unrelated causes of a bypass look identical, and owner-wide capacity, stream status and restarts have no supported interface. Issue #336 asks for one.

## What Changes

- Worker `snapshot()` gains bounded bypass reasons and a separate oversized count. **BREAKING**: shared `bypasses` no longer includes oversized results.
- New `owner_snapshot()` returns owner-wide diagnostics on request, or `None` when the owner does not answer.
- `register_cache_metrics` accepts shared managers and exports worker-local counters only. Owner-scope metrics are deferred to #424.
- The shared FastAPI example, guides, Context7 rules and changelog follow.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `shared-worker-cache`: worker and owner diagnostics, their scopes and failure behavior.
- `otel-metrics`: worker-scope metrics for shared managers.

## Impact

Shared adapters and owner, public exports, the OpenTelemetry bridge and the shared FastAPI example. No dependency, cache-hit work or background activity is added.
