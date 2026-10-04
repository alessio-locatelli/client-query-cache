# Proposal

## Why

The explicit cached views return lists for find and aggregate, requiring read
conversion in consumers written for native cursors. Before adopting a transparent
adapter, decide whether useful cache hits can meet the selected live-error
contract. The selected requirement makes this an execution-equivalence question
before it becomes a driver-wide interface or performance investigation.

## What Changes

- Record the selected requirement: warm reads preserve native server/network
  errors and required server execution effects.
- Explain why a zero-command hit cannot observe a newly introduced native error.
- Retain one directly executable fail-point demonstration and a concise report.
- Distinguish this adoption decision from changing explicit-view return types or
  evaluating a future relaxed contract.

## Capabilities

### New Capabilities

None. This research declares skip_specs: true and changes no runtime behavior.

### Modified Capabilities

None. Existing cached-read behavior remains authoritative.

## Impact

The output is docs/development/research/read-through-collection-adapter-evaluation.md
and research/collection_adapter/live_error.py. The experiment is outside the
package and runs only against an owned disposable MongoDB fixture. Raw outputs
remain untracked. No production fix, generated matrix, integration promise or
production implementation task belongs to this change. Bound-session safety is
handled independently.
