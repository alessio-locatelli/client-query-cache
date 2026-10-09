# Proposal

## Why

Application workers duplicate resident cache values as well as MongoDB change streams. The completed [shared-invalidation study](../../../docs/development/research/shared-invalidation-feasibility.md) did not evaluate shared storage, leaving its memory benefit and access costs unresolved.

## What Changes

- Investigate one optional cache for a group of application processes on one host, following the full development workflow.
- Build a representative research prototype and compare it with independent managers and direct MongoDB reads under the preregistered protocol in [design.md](design.md#measurement-protocol).
- Use the [decision gate](design.md#decision-gate) to choose production integration or an evidence-backed deferral within this change. Neither outcome is predetermined.
- If the gate passes, deliver the conditional behavior specified below and update public guidance; otherwise retain the research report without introducing a supported deployment mode.

## Capabilities

### New Capabilities

- `shared-cache-benchmarking`: Comparable resource, latency, scaling, and failure evidence for shared cached values.
- `shared-worker-cache`: Conditional same-host cache attachment, isolation, transport, recovery, and ownership contracts.

### Modified Capabilities

- `cache-core`: Budget ownership for an attached worker group and the scope of locally inspected shared observations.
- `change-stream-coherency`: Group ownership of invalidation streams, preserving standalone ownership and event semantics.
- `cached-read-api`: Explicit shared attachment through existing managers with native read and cursor behavior preserved.

Production deltas are conditional on the gate. [Outcome handling](design.md#outcome-handling) defines their disposition when integration is rejected.

## Impact

The research extends `benchmarks/stream_cost/` and records its findings under `docs/development/research/`. Conditional integration touches `_core/`, synchronous and asynchronous managers, collections and cursors, public exports, and their tests. A new internal cache-access boundary is expected; transport dependencies and supported operating systems remain candidates until task 3.1 resolves them. The affected public surfaces are the API, consistency, deployment, monitoring and benchmark guides, relevant examples, README, and Context7 rules. No mandatory external cache service or cross-host protocol is proposed.
