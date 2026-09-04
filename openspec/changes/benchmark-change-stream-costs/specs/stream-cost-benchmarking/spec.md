## Purpose

This capability provides controlled, reproducible workload reports for the cost and benefit of change-stream-backed local caching.

## ADDED Requirements

### Requirement: Benchmarks compare equivalent workloads
The benchmark suite SHALL compare raw and coherent-cache variants with identical seeded data, query shapes, read/write mixes, concurrency, duration, warmup, and sample schedules. Every report SHALL identify revision, versions, topology, resource limits, workload parameters, samples, and limitations.

#### Scenario: A paired workload is reported
- **WHEN** a benchmark writes a raw-versus-cache comparison report
- **THEN** the validator rejects it if either variant lacks a required matching workload parameter

### Requirement: Controlled measurements are not generalized
The suite SHALL report monotonic wall time, benchmark-process CPU, and controlled MongoDB-container CPU where available. Optional byte-proxy mode SHALL count only its direct benchmark path and SHALL refuse unsupported TLS, compression, discovery, or shared-connection configurations. CI SHALL retain reports without using timing as a host-dependent pass/fail gate.

#### Scenario: Proxy mode is requested with compression
- **WHEN** a benchmark requests byte-proxy mode with compression enabled
- **THEN** the benchmark refuses the configuration rather than labelling its bytes as an unambiguous direct-path measure
