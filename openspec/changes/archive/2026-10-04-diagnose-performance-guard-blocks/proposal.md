# Proposal

## Why

[PR 152 guard failure](https://github.com/alessio-locatelli/client-query-cache/actions/runs/37212162625/job/111465505940?pr=152) rejected all four hit cases during duration validation, discarded their timing arrays, and left the step log without an explanation. The generic reason and missing timings prevent distinguishing short blocks from nonfinite durations. Retaining rejection evidence will identify the cause.

## What Changes

- Preserve completed paired measurements when evaluation rejects them.
- Identify the revision side, block number, rejected duration, and minimum duration in evaluation errors.
- Display the existing summary in both the step log and GitHub job summary.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `performance-regression-guard`: retain rejected timings and expose rejection reasons in CI logs.

## Impact

Guard evaluation, reports, CI output, and developer documentation. Workload sizes, failure policy, and slowdown threshold remain unchanged.
