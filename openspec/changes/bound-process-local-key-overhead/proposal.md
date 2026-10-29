# Proposal

## Why

The BSON budget leaves retained query keys and entry bookkeeping unbounded by a separate capacity policy. [Issue #337](https://github.com/alessio-locatelli/client-query-cache/issues/337) requests a practical safeguard; its historical memory measurements motivate the work without establishing current native-cache costs or a leak.

## What Changes

- Add opt-in limits for retained value/alias records and accounted key size, preserving native read delivery when admission is declined.
- Expose capacity and decline observations through the existing inspection interfaces.
- Qualify footprint and affected read costs using focused existing memory workloads.

## Implementation sequencing

The implementation follows `migrate-remaining-hotpaths-to-rust`: it builds on that migration's preparation and residency seams and is qualified against the resulting main, which is frozen as the control. The [resource report](../../../reports/process-memory/summary.md#retention-safeguards-qualification-on-2026-11-02) records the safeguard's incremental costs. Keep this change active and unarchived until those costs are accepted.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cache-core`: Define retention limits, their accounting and lifecycle.
- `cached-read-api`: Align unique-key admission and lookup with configured pair/fallback retention while preserving one read outcome.
- `public-library-documentation`: Explain how to configure the safeguard and distinguish its guarantee from process-memory limits.

## Impact

The implementation crosses the native local owner, Python reference core, shared-owner configuration/snapshot adapters, public configuration and statistics, and the process-memory harness. No dependency or shared wire-format redesign is proposed. Shared-cache capacity policy remains separate. Contract details belong to the delta specs; implementation decisions and qualification procedure belong to `design.md`.
