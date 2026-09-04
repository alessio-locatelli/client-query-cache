## Purpose

This capability provides controlled, reproducible workload reports for the cost and benefit of change-stream-backed local caching.

## ADDED Requirements

### Requirement: Benchmarks compare equivalent workloads
The benchmark suite SHALL compare raw and coherent-cache variants with identical seeded data, query shapes, read/write mixes, concurrency, duration, warmup, and sample schedules. Before sampling each workload variant, including each workload/data-size combination, the cache variant SHALL run its configured warmup through the normal coherent-cache admission path and SHALL verify positive counter deltas for at least one cache admission and one cache hit for that variant. The benchmark SHALL fail setup or report validation when a sampled variant lacks those counter deltas. Every report row SHALL identify the corresponding warmup counter deltas, and every report SHALL identify revision, versions, topology, resource limits, workload parameters, samples, and limitations.

#### Scenario: A paired workload is reported
- **WHEN** a benchmark writes a raw-versus-cache comparison report
- **THEN** the validator rejects it if either variant lacks a required matching workload parameter

### Requirement: Controlled measurements are not generalized
The suite SHALL report monotonic wall time, benchmark-process CPU, and controlled MongoDB-container CPU for every controlled run. If MongoDB-container CPU cannot be collected from the configured cgroup or runtime, setup SHALL fail and the run SHALL not produce a controlled report. Optional byte-proxy mode SHALL count only its direct benchmark path and SHALL refuse unsupported TLS, compression, discovery, or shared-connection configurations. CI SHALL retain reports without using timing as a host-dependent pass/fail gate.

#### Scenario: Proxy mode is requested with compression
- **WHEN** a benchmark requests byte-proxy mode with compression enabled
- **THEN** the benchmark refuses the configuration rather than labelling its bytes as an unambiguous direct-path measure

#### Scenario: A workload variant is not primed
- **WHEN** a cache workload variant completes warmup without positive counter deltas for at least one cache admission and one cache hit for that variant
- **THEN** setup or report validation fails before sampled results are accepted

#### Scenario: Controlled container CPU is unavailable
- **WHEN** a controlled benchmark cannot collect MongoDB-container CPU from its cgroup or runtime
- **THEN** setup fails and the benchmark does not emit a controlled report with an incomplete CPU measurement
