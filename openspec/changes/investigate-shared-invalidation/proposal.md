# Proposal

## Why

[Issue #87](https://github.com/alessio-locatelli/client-query-cache/issues/87) asks whether duplicated change-stream costs justify shared invalidation delivery across worker processes. The library has no multi-process measurements establishing that trade-off, so an investigation should precede a supported coordination feature.

## What Changes

- Add reproducible multi-process measurements and a bounded research prototype for sharing invalidations while keeping cached values local.
- Produce a feasibility report comparing coordination alternatives and their continuity, recovery, and operating costs, with an evidence-based recommendation to defer or pursue a separate implementation proposal.
- Keep this change limited to research: no supported shared coordinator, distributed result cache, public API change, or production transport dependency.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `stream-cost-benchmarking`: Add multi-process cost attribution and shared-invalidation feasibility evidence requirements.

## Impact

The implementation will extend `benchmarks/stream_cost/` and its benchmark tests, and add a research reference under `docs/development/research/`. Existing manager, stream-coherency, and public usage contracts remain authoritative.
