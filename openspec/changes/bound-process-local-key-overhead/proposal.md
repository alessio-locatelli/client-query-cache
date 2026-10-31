# Proposal

## Why

The BSON budget leaves retained query keys and entry bookkeeping unbounded by a separate capacity policy. [Issue #337](https://github.com/alessio-locatelli/client-query-cache/issues/337) requests a practical safeguard; its historical memory measurements motivate the work without establishing current native-cache costs or a leak.

## What Changes

- Add opt-in limits for retained value/alias records and accounted key size, preserving native read delivery when admission is declined.
- Expose capacity and decline observations through the existing inspection interfaces.
- **BREAKING**: Rename `shared_budget_bytes` to `budget_bytes` without a compatibility alias, including configuration, snapshots, validation and maintained usage references.
- Qualify footprint and affected read costs using focused existing memory workloads.

## Implementation sequencing

Preserve the current implementation, tests and measurements as a checkpoint. Further implementation and performance qualification wait until `migrate-remaining-hotpaths-to-rust` lands. The measured regressions in the [resource report](../../../reports/process-memory/summary.md#retention-safeguards-qualification-on-2026-10-29) remain unaccepted.

Resume by rebasing onto that migration, freezing its resulting main as the new control, and measuring the safeguard's incremental costs. Retain the selected public contract, including the budget-name migration. Keep this change active and unarchived until its remaining qualification task is complete.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cache-core`: Define retention limits, their accounting and lifecycle, and the public BSON-budget name.
- `cached-read-api`: Align unique-key admission and lookup with configured pair/fallback retention while preserving one read outcome.
- `public-library-documentation`: Explain how to configure the safeguard and distinguish its guarantee from process-memory limits.

## Impact

The implementation crosses the native local owner, Python reference core, shared-owner configuration/snapshot adapters, public configuration and statistics, and the process-memory harness. No dependency or shared wire-format redesign is proposed. Shared-cache capacity policy remains separate. Contract details belong to the delta specs; implementation decisions and qualification procedure belong to `design.md`.
