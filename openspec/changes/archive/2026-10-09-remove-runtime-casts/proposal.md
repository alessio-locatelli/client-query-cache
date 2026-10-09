# Proposal

## Why

`typing.cast()` adds a Python call while returning its argument unchanged. Recurring library reads currently pay this cost despite the contributor rule forbidding it on hot paths.

## What Changes

- Remove casts from library source and recurring application/example and benchmark paths.
- Record the existing contributor restriction in the type-annotations specification.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `type-annotations`: Define where runtime casts are permitted.

## Impact

Sync and async collection/cursor integration, core decoding, and affected examples and benchmark instrumentation. Public values, validation, native exceptions, and dependencies remain unchanged.
