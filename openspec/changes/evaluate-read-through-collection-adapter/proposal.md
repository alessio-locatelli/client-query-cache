# Proposal

## Why

The list-returning cached views require application changes when switching to native PyMongo, and the delivered integrations copy upstream decoding and validation to adapt reads. A collection adapter needs practical evidence that each public method and its accepted argument combinations preserve PyMongo behavior, or a reproducible explanation of why compatibility is infeasible.

## What Changes

- Produce a versioned inventory of public synchronous and asynchronous PyMongo collection methods, their arguments, and interacting argument combinations. Use released driver contracts to justify complete behavioral partitions rather than claiming that a finite sample exhausts arbitrary input values.
- Assign every case one evidenced outcome: compatible cached execution, compatible uncached forwarding, or a documented rejection with a runnable prototype or minimal reproducible example establishing the specific incompatibility and why forwarding cannot preserve the contract.
- Evaluate an opt-in adapter with the same application calls against raw PyMongo and cache-disabled, miss, hit, bypass, and invalidated states. Disabling caching must not require changing method calls, cursor consumption, or awaiting conventions.
- Build real cursor-returning `find` experiments and investigate the other cache-aware reads, writes, administration, collection traversal, options, ownership, errors, and typing. Preserve native operation behavior when caching is unsafe; inability to cache is not grounds for rejecting a valid PyMongo operation.
- Measure bounded additional cache buffering, first-document latency, full-result cost, and concurrent-cursor memory against raw PyMongo and eager materialization. Admit only complete results whose invalidation guards remain valid.
- Retain requests-cache, Celery, py-abac, and Eve as integration checks against the driver-wide inventory. Consumer usage does not define or reduce the compatibility contract.
- Record a reproducible feasibility report and one adoption recommendation. Distinguish demonstrated incompatibility, prototype defects, unverified cases, and performance or maintenance trade-offs. A production implementation requires a subsequent proposal based on the evidence.

## Capabilities

### New Capabilities

None. This feasibility study changes no library behavior; `.openspec.yaml` declares `skip_specs: true`.

### Modified Capabilities

None. The current `cached-read-api` contract remains authoritative.

## Impact

Committed output is `docs/development/research/read-through-collection-adapter-evaluation.md`, containing the inventory, compatibility evidence, reproducible experiment sources and commands, concise measurements, rejection demonstrations, and the recommendation. Experiment files and raw measurements stay untracked under `/tmp`. No production package, public example, dependency manifest, workflow, submodule, or upstream project is modified. The active examples change retains ownership of its Eve example. This change remains an investigation; it does not publish a compatible adapter or alter the existing read-view specification.
