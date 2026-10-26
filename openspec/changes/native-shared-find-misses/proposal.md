# Proposal

## Why

The current-release investigation for [#341](https://github.com/alessio-locatelli/client-query-cache/issues/341) identifies a repeatable cold sorted-find cost: every read prepares two wire keys and selects through the owner before MongoDB. Native family absence checks and locally fenced capture can remove that control exchange; the measured baseline and attribution belong in `reports/shared-worker-cache/current-costs/results.md`.

## What Changes

- Retain native exact find hits and authorize definite misses through a bounded family filter; retain owner selection for compatible limits.
- Preserve authoritative owner admission and fallback when native publication is incomplete.
- Use focused, preregistered current-release comparisons for this scoped miss optimization; do not claim historical protocol requalification.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `shared-worker-cache`: native find selection, bounded publication completeness and cursor admission.
- `shared-cache-benchmarking`: namespace capture scenarios and scoped optimization evidence.

## Impact

Native index layout and bindings, shared publisher/adapters/coordinator, protocol tests and models, internal architecture guidance and benchmark evidence. Public constructors, query eligibility and consistency remain unchanged. No new dependency or public setting is proposed.
