# Proposal

Disposition: **public barrier deferred; implementation rejected for inclusion.** This change closes as a
documentation-only outcome, not as delivery of the originally proposed API.

## Why

The barrier investigation identified a narrow supported use case and substantial latency and integration
constraints. Preserve the decision and useful evidence in the maintained repository so future agents do not
resume the implementation merely because its original plan remains active.

## What Changes

- Record the consistency decision in `docs/decisions/defer-causal-invalidation-barrier.md`.
- Curate the investigation in `docs/causal-invalidation-barrier-research.md`, separating documented contracts,
  reported observations, and assumptions that require validation before reconsideration.
- Link both documents from the architecture guide, including the low-priority integration research trigger.
- Withdraw the proposed barrier delta and runtime tasks. Preserve PR #124 and immutable source links as
  references, then archive this change with its documentation-only disposition.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. The existing eventual coherency and session-bound read bypass contracts remain authoritative.
The change declares `skip_specs: true` because no supported behavior changes.

## Impact

Documentation and this change's planning artifacts only. The implementation in
[PR #124](https://github.com/alessio-locatelli/client-query-cache/pull/124), branch
`add-causal-invalidation-barrier`, is reference material rather than an implementation to merge.
