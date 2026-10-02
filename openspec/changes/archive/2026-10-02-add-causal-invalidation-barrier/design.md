# Design

## Context

See `proposal.md` for the disposition. The maintained coherency specification already permits stale hits until
the relevant event is processed, and session-bound reads bypass the cache. The original barrier implementation
and measurements remain accessible through PR #124; they do not establish a product need for the API.

## Goals / Non-Goals

**Goals:** Make the decision discoverable from current documentation and preserve enough evidence to avoid
repeating the investigation without a concrete application requirement.

**Non-Goals:** Shipping a barrier, changing cache consistency, populating the cache from writes, rerunning the
historical benchmark matrix, or fixing independent runtime findings in this documentation change.

## Decisions

### Separate the durable decision from experimental evidence

Use `docs/decisions/defer-causal-invalidation-barrier.md` for rationale, alternatives, consequences, and
reconsideration criteria. Use `docs/causal-invalidation-barrier-research.md` for sources, observations, technical
assumptions, and reproduction guidance. The architecture guide links to both; discovery does not depend on a
future agent finding an unmerged branch.

### Withdraw the implementation plan

Replace runtime tasks with the documentation deliverables, delete the unimplemented barrier delta, and declare
`skip_specs: true`. Main specifications describe supported behavior and receive no barrier requirements.
The archive explicitly records a deferred feature rather than implying successful runtime completion.
Future implementation requires a newly scoped change justified by a concrete application.

## Risks / Trade-offs

- Historical observations may be mistaken for guarantees: label their provenance and validation limits.
- Closing the feature may hide an independent defect: retain the asyncio timeout-context finding with its
  source and independent follow-up scope in the research report.
- Source branches may disappear: link to immutable PR commit paths as well as the PR itself.

## Migration Plan

Land the documentation-only outcome from a branch based on `main`. No runtime or stored-data migration is needed.
