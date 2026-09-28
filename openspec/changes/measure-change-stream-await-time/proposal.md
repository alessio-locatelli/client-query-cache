# Proposal

## Why

The manager currently supplies a 1,000 ms change-stream await time without a measured basis for that choice. Idle `getMore` traffic has a resource cost, while increasing the wait may affect failure detection, shutdown, and caller timeouts; the library needs a reproducible decision and a way for deployments with different constraints to override it.

## What Changes

- Compare several await times under matched idle and active change-stream workloads, including the current 1,000 ms baseline. Retain the measured decision evidence and the rule used to choose a default.
- Apply the selected default to synchronous and asynchronous managers, and offer a validated, per-manager public override. Do not read an environment variable for this setting.
- Document the selected value, its measured rationale and limits, and the relationship to PyMongo timeouts in the API and performance guidance.
- Correct the scope of the existing `stream_polls` measurement so it is not used as a count of MongoDB `getMore` commands.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `stream-cost-benchmarking`: Require a matched await-time comparison, a pre-registered selection rule, and retained decision evidence.
- `change-stream-coherency`: Specify the shared default and validated per-manager override for both execution models.
- `stream-cost-observability`: Clarify what the existing stream-poll counter counts and require actual `getMore` observation for this benchmark.

## Impact

The change affects both stream supervisors and `CacheManager` constructors, benchmark instrumentation and reports, tests, and public API and performance documentation. It adds no dependency or process-wide configuration source.
