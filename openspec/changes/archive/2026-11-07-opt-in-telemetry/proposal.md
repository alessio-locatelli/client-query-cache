# Proposal

## Why

Cache and change-stream operations collect diagnostic data even when applications never inspect it. The default must avoid that work; there is no evidence establishing package adoption or telemetry usage, so this proposal does not assume either.

## What Changes

- **BREAKING**: Introduce the collection policy defined in the [telemetry-control delta](specs/telemetry-control/spec.md).

## Capabilities

### New Capabilities

- `telemetry-control`: Collection policy, disabled-path guarantees, diagnostic access and shared-server propagation.

### Modified Capabilities

- `cache-core`: Condition observation contracts on collection being enabled.
- `shared-worker-cache`: Condition worker and owner diagnostics on collection being enabled.
- `stream-cost-observability`: Condition stream measurement on collection being enabled.
- `otel-metrics`: Reject registration against disabled sources before creating instruments.

## Impact

This affects configuration, Python and Rust cores, synchronous and asyncio stream supervision, shared-server attachment configuration, diagnostics, tests, examples and public usage rules. No dependency or production-service changes are required. The [design](design.md) owns the audit, architecture and validation constraints; the [tasks](tasks.md) own implementation and consumer updates.
