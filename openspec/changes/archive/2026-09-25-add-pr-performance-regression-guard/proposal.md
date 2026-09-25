# Proposal

## Why

The required pull-request checks validate benchmark machinery but do not compare the proposed cache implementation with its base revision. The manual stream-cost workflow records useful cost evidence for one revision, yet a material slowdown in a shipped hot path can pass CI without any timing comparison.

## What Changes

- Add a required, lightweight relative regression guard for selected cache hot paths on pull requests that change Python code or its runtime dependencies.
- Measure base and proposed implementations under matched conditions on one runner, and fail only for a clear, material slowdown. Preserve diagnostic evidence when a comparison fails or cannot be made.
- Keep the controlled stream-cost reports and architectural decision evidence in the manual workflow; refine their specification to distinguish their prohibition on absolute host-dependent timing gates from the new paired relative guard.
- Document the guard's coverage, interpretation, and process for an intentional performance trade-off without a routine manual benchmark checkbox.

## Capabilities

### New Capabilities

- `performance-regression-guard`: Pull-request coverage, comparable base-versus-head measurements, conservative failure decisions, and actionable diagnostics for shipped cache hot paths.

### Modified Capabilities

- `stream-cost-benchmarking`: Clarify that its controlled report timings remain evidence rather than absolute CI thresholds, while allowing a separately specified matched relative guard.

## Impact

The change affects `benchmarks/stream_cost/`, its benchmark tests, pull-request CI, and performance guidance in `docs/`. It uses the existing workload fixtures, cache and stream outcome counters, and benchmark measurement concepts where they fit. It does not change the library's public API, require an external performance service, or make the full controlled workload matrix mandatory for each pull request.
