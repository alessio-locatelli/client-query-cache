# Proposal

## Why

Comparison-only configuration validation accepts NaN and non-integer values, undermining bounded cache storage and lag telemetry. Invalid runtime input should fail at configuration construction with the library's configuration error.

## What Changes

- **BREAKING** for invalid inputs: require exact built-in integers for cache budgets and lag-window counts, excluding booleans and integer subclasses.
- Retain the existing valid ranges and defaults.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `cache-core`: budget configuration type and range validation.
- `stream-cost-observability`: lag-window configuration type and range validation.

## Impact

`CacheCoreConfig`, `LagCaptureWindowConfig`, their existing test files, configuration reference, and affected Context7 rules. Validation happens at construction, outside read and invalidation hot paths.
