# Proposal

## Why

[Issue #278](https://github.com/alessio-locatelli/client-query-cache/issues/278) asks whether shared-cache acceptance studies spend more time than their statistical reliability requires. The published studies establish outcomes, but do not establish a minimum useful experimental cost.

## What Changes

- Add a reproducible exploratory runtime and precision investigation, with its decision criteria fixed before alternative comparisons.
- Publish a recommendation grounded in retained observations, analytical bounds and simulations with known effects.

## Capabilities

No requirement changes. This research change sets `skip_specs: true`; existing registrations and acceptance behavior remain authoritative.

## Impact

Standalone research tooling and a report under `reports/shared-worker-cache/runtime/`. No library, benchmark runner, dependency lockfile or version 7/8 registration changes. The separate miss-cost change and issue #272 keep their existing outcomes.
