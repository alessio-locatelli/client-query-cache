# Proposal

## Why

Adopters must piece together consistency, eligibility, operating costs, and upgrade risks across several guides. The existing FastAPI integration demonstrates these concerns but is too large for a quick evaluation.

## What Changes

- Add a concise adoption decision guide, linked to canonical contracts and measured capacity guidance.
- Provide a small FastAPI application and a runnable self-check that exposes cache outcomes and eventual invalidation.
- Connect eligibility examples to public counters, and document a disposable permission-recovery exercise.
- Explain reproducible dependency selection and testing PyMongo upgrades.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `public-library-documentation`: Adoption decisions, worked eligibility observations, permission recovery, and dependency upgrade guidance.
- `usage-examples`: Compact FastAPI integration with observable outcome verification.

## Impact

Public guides, navigation, the example catalogue, a new inline-dependency example, and its existing subprocess verification. No package runtime API or project dependencies change. Multi-worker launches and timed recovery measurements remain owned by the existing `benchmark-concurrent-worker-workload` and `benchmark-worker-fault-recovery` changes.
