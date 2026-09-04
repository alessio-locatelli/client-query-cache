## Context

Generic benchmark execution is part of the test bootstrap. This change starts only after cached reads and stream coherency exist and owns the specialised workload, telemetry, and report contract.

## Goals / Non-Goals

**Goals:** Measure logical cache benefit, stream activity, controlled CPU, and optional direct-path bytes across reproducible workloads.

**Non-Goals:** This change does not claim Atlas or production-server CPU, measure encrypted/compressed wire traffic, or automatically disable caches.

## Decisions

- Keep logical manager counters separate from network and server metrics.
- Use a dedicated local replica-set benchmark topology, resource limits, and client; make unavailable cgroup/runtime evidence an explicit setup failure.
- Compare paired raw and cache variants over idle, read-heavy, balanced, and write-dominant workloads with small/medium/large BSON data. Prime each coherent-cache workload/data-size variant through normal reads, require positive admission and hit counter deltas for that variant before collecting its samples, and retain those deltas with the corresponding report row. Include consolidated-stream workloads with exactly one database-scoped stream serving at least two cached collections in one database, and separately measure writes relevant to the measured cache entries and writes to unrelated collections in that same database. Record per-variant latency distributions with cache-outcome labels alongside aggregate timing for operation-bearing variants; represent idle variants with zero operations and an explicit no-latency-samples marker.
- Use an optional dedicated TCP proxy only when TLS, compression, discovery, and shared connections are disabled; call its result path bytes, not universal wire bytes.
- Upload reports in opt-in CI without timing regression gates.

## Risks / Trade-offs

- [Environment noise corrupts conclusions] → Record environment and samples, control resources, and avoid cross-host thresholds.
- [Projection removes an event needed for invalidation] → Test every event type and resume path against functional coherency before measuring.

## Migration Plan

Add telemetry first, then schema/validator and controlled topology, then workloads and retained reports with documented interpretation limits.
