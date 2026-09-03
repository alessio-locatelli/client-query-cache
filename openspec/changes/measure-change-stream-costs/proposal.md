## Why

The library's value depends on a workload-specific trade-off: cache hits avoid
MongoDB reads, while change streams consume a held connection, event bandwidth,
server work, and local CPU. The repository currently has no benchmark harness
or stream-cost measurements, so its README claim that it is benchmarked and
stress tested is unsupported.

## What Changes

- Add runtime stream-cost and cache-benefit telemetry that distinguishes logical
  event payloads and cache behavior from wire-level network measurements.
- Define an invalidation-only database stream projection that retains the event
  resume token, namespace, operation type, and document key while excluding
  unneeded full documents. The projection remains broad enough to process every
  event required by document and derived-result invalidation.
- Add a reproducible local replica-set benchmark harness that compares raw
  primary/majority reads with warm cached reads, measures idle and write-active
  stream behavior, and reports client CPU, controlled-server CPU, latency,
  logical event data, and optional wire bytes.
- Publish a versioned benchmark protocol and evidence-based workload guidance;
  reports will identify the environment and workload, not advertise universal
  performance or break-even claims.
- Keep automatic cache disabling out of scope until measured evidence and a
  separately specified product policy justify it.

## Capabilities

### New Capabilities

- `stream-cost-observability`: Exposes trustworthy cache-benefit and
  change-stream activity measurements to applications without claiming that
  logical payload size equals encrypted/compressed wire traffic.
- `stream-cost-benchmarking`: Provides a repeatable benchmark and measurement
  protocol for deciding when a consolidated database change stream is useful.
- `invalidation-stream-projection`: Defines the minimal event shape required by
  the cache's invalidation semantics while preserving resumability.

### Modified Capabilities

- None. The repository has no archived OpenSpec capability specifications; the
  related foundation change remains an unimplemented planning change.

## Impact

- Affected planned implementation: the cache manager and stream supervisor from
  `bootstrap-client-cache-foundation` gain event-payload accounting and a
  validated invalidation-only stream pipeline. The benchmark work depends on
  that foundation being implemented first.
- Affected public behavior: cache inspection gains clearly scoped cost and
  benefit counters. No automatic performance-based disabling is introduced.
- Affected tooling: integration fixtures grow a dedicated measurement topology,
  repeatable workload generator, result schema, and optional wire-byte proxy.
- Affected documentation: the unsupported performance claim is removed until
  reproducible reports exist, then replaced with workload-specific guidance and
  links to versioned results.
