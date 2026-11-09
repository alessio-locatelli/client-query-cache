# Proposal

## Why

The production managers use native cache engines, but the package still contains a second Python engine and native facilities whose only consumers are tests, benchmarks, or research. This obscures the production architecture, adds maintenance work, and caused the selective-invalidation plan to target the wrong implementation.

## What Changes

- Enforce the production-purpose boundary in `specs/production-library-scope/spec.md` and remove its inventoried violations completely.
- Convert remaining verification and measurements to production behavior under the revised evaluation requirements, without retaining a comparison engine elsewhere.
- Correct current architecture guidance and reconcile the existing selective-invalidation plan with the production owner.

## Capabilities

### New Capabilities

- `production-library-scope`: Permitted contents of the library and separation of development tooling from application implementation.

### Modified Capabilities

- `process-local-cache-evaluation`: Contract-based native verification and isolated installed-build comparisons.

## Impact

See `design.md` D1–D3 for the concrete deletion and consumer inventory. Affected areas include the Python package, native extension bindings, native binding tests, PGO workloads, current benchmark commands, documentation, and the active `opt-in-selective-invalidation` artifacts. The public manager/configuration exports and supported application behavior remain the compatibility boundary; removed private reference and instrumentation interfaces receive no compatibility shims.
