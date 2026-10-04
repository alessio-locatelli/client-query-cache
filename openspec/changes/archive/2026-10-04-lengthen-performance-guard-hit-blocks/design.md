# Design

## Context

See `proposal.md` for the failed CI measurements. The base revision supplies
the workload to both environments. Hit cases prime one query, time a fixed
batch, and verify the results, hit counter, and absence of bypasses.

## Goals / Non-Goals

Provide a substantial duration margin on the observed runner while keeping
the workload bounded. Automatic calibration and guard policy changes are
outside this change.

## Decisions

Increase the shared hit batch from 256 to 2,048 operations, subject to local
fresh-process verification. Eight times the observed roughly 4.5 ms duration
provides more margin than doubling the batch. A fixed batch preserves equal
work across revisions without introducing an adaptive calibration protocol.
Lowering the validity floor would instead accept the inadequate measurements.

Measure both hit cases and both guard profiles in six fresh processes per
configuration, using the existing paired runner and isolated replica set.
Retain the existing result and counter checks. Run the guard's existing tests
to verify that invalid measurements still fail and decisions remain unchanged.

## Risks / Trade-offs

- Longer batches retain more result objects and add runtime. The operation
  count remains bounded; measure the added timed work before accepting it.
- Local hardware differs from CI. Record local measurements separately from
  the CI artifact, rather than claiming local timings predict CI exactly.
- A PR uses its base workload even when it changes that workload. Deployment
  therefore requires the existing maintainer-controlled measurement-failure
  exception if the old batches fail again; merging activates the new batches.

## Migration Plan

Merge the calibrated workload. Reverting its operation count restores the
previous workload without changing stored data or library behavior.
