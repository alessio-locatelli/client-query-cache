## Why

The current experimental client subclasses and undocumented behavior are not a safe base for a public library. Before adding cache features, the project must establish an explicit replacement boundary and preserve raw PyMongo escape hatches.

## What Changes

- Audit the proof-of-concept public surface and classify supported, replaced, and removed behavior.
- Replace inheritance-based cached clients with composed manager and collection-facade construction seams.
- Provide migration and compatibility guidance without claiming production-ready cache semantics.

## Capabilities

### New Capabilities

- `prototype-recovery`: Safe migration from the experimental proof of concept to the supported construction model.

### Modified Capabilities

- None.

## Impact

- Affects package exports, construction APIs, compatibility tests, and migration documentation; it depends on the bootstrap environment and test foundation.
