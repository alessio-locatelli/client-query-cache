# Proposal

## Why

[Issue #278](https://github.com/alessio-locatelli/client-query-cache/issues/278) asks whether shared-cache acceptance studies spend more time than their statistical reliability requires. The published studies establish outcomes, but do not establish a minimum useful experimental cost.

## What Changes

- Add a reproducible exploratory runtime and precision investigation, with its decision criteria fixed before alternative comparisons.
- Publish a recommendation grounded in retained observations, analytical bounds and simulations with known effects.
- Validate the selected acquisition reduction with fresh baseline qualification and active-window comparisons; preregister the resulting version 9 protocol before future candidate timing.

## Capabilities

No library requirement changes. This research change sets `skip_specs: true`; version 9 changes future baseline acquisition only. Existing studies remain frozen.

## Impact

Standalone research tooling, reports under `reports/shared-worker-cache/runtime/` and a version 9 protocol preregistration. Slotscheck excludes isolated numerical analyses from project-environment imports. Benchmark environment recording accepts additional research source paths. No library, dependency lockfile or version 7/8 registration changes. The separate miss-cost change and issue #272 keep their existing outcomes.
