# Proposal

## Why

The delivered integrations copy upstream decoding and validation just to change the receiver of a read. Forwarding writes from the existing cached view would not solve native cursor behavior and would revisit the deliberately removed untyped forwarding, so a separate adapter needs evidence before becoming a public API.

## What Changes

- Produce a versioned compatibility matrix and a reproducible feasibility report for requests-cache, Celery, py-abac, and Eve, using the current explicit read views as the baseline.
- Evaluate an opt-in collection adapter without changing the existing cached-view contract, temporarily replacing shared receivers during operations, or misrepresenting types.
- Prototype the smallest consumer-required cursor/collection contract in isolated, untracked experiments; assess writes/admin calls, options, ownership, cursor chaining and partial consumption, sync/async behavior, and native tooling.
- Measure bounded additional cache buffering and compare it with the current eager materialization behavior. Preserve complete results when caching is declined; never admit incomplete results.
- Record a decisive go/no-go outcome and the precise supported contract. A go decision is input to a separately authorized production proposal, not authorization to ship an adapter in this change.

## Capabilities

### New Capabilities

None. This feasibility study changes no library behavior; `.openspec.yaml` declares `skip_specs: true`.

### Modified Capabilities

None. The current `cached-read-api` contract remains authoritative.

## Impact

Committed output is a report under `docs/` with source revisions, commands, concise measurements, limitations, and the decision. Experiments and raw measurements stay untracked. No production package, public example, dependency manifest, workflow, submodule, or upstream project is modified. The active examples change retains ownership of its Eve example; this study assesses compatibility without duplicating that implementation obligation. Other proposed changes are optional experimental comparisons, not prerequisites for finishing the study.
