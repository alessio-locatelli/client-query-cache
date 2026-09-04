## Purpose

This capability provides controlled, reproducible workload reports for the cost and benefit of change-stream-backed local caching.

## ADDED Requirements

### Requirement: Benchmarks compare equivalent workloads
The benchmark suite SHALL compare raw and coherent-cache variants with identical seeded data, query shapes, read/write mixes, concurrency, duration, warmup, and sample schedules. Before sampling each workload variant, including each workload/data-size combination, the cache variant SHALL run its configured warmup through the normal coherent-cache admission path and SHALL verify positive counter deltas for at least one cache admission and one cache hit for that variant. The benchmark SHALL fail setup or report validation when a sampled variant lacks those counter deltas. Every report row SHALL identify the corresponding warmup counter deltas, and every report SHALL identify revision, versions, topology, resource limits, workload parameters, samples, and limitations.

#### Scenario: A paired workload is reported
- **WHEN** a benchmark writes a raw-versus-cache comparison report
- **THEN** the validator rejects it if either variant lacks a required matching workload parameter

### Requirement: Consolidated-stream workloads cover topology and traffic
For measurements intended to characterize the consolidated database-scoped stream, the workload matrix SHALL configure exactly one database-scoped stream serving at least two cached collections in the same database. It SHALL separately identify writes to measured cached collections whose events can invalidate the measured entries and writes to collections outside the measured cached set but in that same database. The workload parameters and report SHALL record the exact stream count, collection-to-stream mapping, and the counts or rates for relevant and unrelated writes.

#### Scenario: A consolidated stream is characterized
- **WHEN** a benchmark report claims to measure the cost of one database-scoped stream across cached collections
- **THEN** setup or report validation rejects it unless exactly one stream serves at least two cached collections in one database, the unrelated writes target collections in that same database, and the report records its collection-to-stream mapping plus both relevant and unrelated write traffic

### Requirement: Reports preserve per-variant latency distributions
For every raw/cache pair and operation-bearing workload/data-size combination, the benchmark SHALL record operation-latency samples or a distribution for each variant. Cache-variant latency data SHALL be associated with the observed cache outcome, and raw-variant latency data SHALL be associated with the raw variant. Each report row for an operation-bearing variant SHALL preserve enough distribution data to compare variants, including sample count and at least p50, p95, and p99 latency values. An idle variant SHALL instead record zero operations and an explicit no-latency-samples marker for each variant.

#### Scenario: A report has only aggregate timing
- **WHEN** a benchmark report includes total wall time but lacks per-variant latency distributions associated with cache outcomes
- **THEN** report validation rejects the report as insufficient for an operation-bearing workload's cache cost and benefit conclusions

### Requirement: Controlled measurements are not generalized
The suite SHALL report monotonic wall time, benchmark-process CPU, and controlled MongoDB-container CPU for every controlled run. For every operation-bearing variant in a controlled run, it SHALL report the required per-variant latency distribution; an idle variant SHALL report the explicit zero-operation and no-latency-samples marker. If MongoDB-container CPU cannot be collected from the configured cgroup or runtime, setup SHALL fail and the run SHALL not produce a controlled report. Optional byte-proxy mode SHALL count only its direct benchmark path and SHALL refuse unsupported TLS, compression, discovery, or shared-connection configurations. CI SHALL retain reports without using timing as a host-dependent pass/fail gate.

#### Scenario: Proxy mode is requested with compression
- **WHEN** a benchmark requests byte-proxy mode with compression enabled
- **THEN** the benchmark refuses the configuration rather than labelling its bytes as an unambiguous direct-path measure

#### Scenario: A workload variant is not primed
- **WHEN** a cache workload variant completes warmup without positive counter deltas for at least one cache admission and one cache hit for that variant
- **THEN** setup or report validation fails before sampled results are accepted

#### Scenario: Controlled container CPU is unavailable
- **WHEN** a controlled benchmark cannot collect MongoDB-container CPU from its cgroup or runtime
- **THEN** setup fails and the benchmark does not emit a controlled report with an incomplete CPU measurement
