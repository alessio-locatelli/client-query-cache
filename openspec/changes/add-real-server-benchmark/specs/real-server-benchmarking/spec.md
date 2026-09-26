# Spec Delta

## Purpose

This capability measures the cache's real-world benefit and guards against regressions against a real, externally hosted MongoDB deployment, complementing the disposable local replica set used by every other test tier.

## ADDED Requirements

### Requirement: A benchmark exercises a real external MongoDB deployment

The repository SHALL provide a benchmark test that connects to a real, externally hosted MongoDB replica set using a connection string sourced from the contributor's local, gitignored configuration rather than from repository state or a disposable container.

#### Scenario: A contributor with a configured real deployment runs the local benchmark command

- **WHEN** a contributor with a configured real-deployment connection string runs the documented local benchmark command
- **THEN** the benchmark connects to that real deployment and executes its workload against it

### Requirement: The benchmark only runs in a runnable local environment

The benchmark SHALL skip, with a visible and explicit reason, whenever it runs in CI or whenever no real-deployment connection string is configured locally. It SHALL NOT fail the surrounding test command in either case, and it SHALL NOT attempt a network connection when skipping.

#### Scenario: CI runs the documented local benchmark command

- **WHEN** the documented local benchmark command runs in CI
- **THEN** the benchmark reports an explicit skip and the command's overall result is unaffected by the benchmark

#### Scenario: A contributor without a configured real deployment runs the documented local benchmark command

- **WHEN** a contributor without a configured real-deployment connection string runs the documented local benchmark command
- **THEN** the benchmark reports an explicit skip identifying the missing configuration, and every other test in the command continues to run

### Requirement: The benchmark workload models concurrent independent applications within a small shared deployment's limits

The benchmark's workload SHALL run a writing/updating workload and a reading workload as independent, concurrently running processes against the same real deployment, modeling two independent application components sharing one database. The workload's size and rate SHALL stay within the throughput and storage limits of a small, shared, free-tier deployment, and the benchmark SHALL complete in under 20 seconds.

#### Scenario: The benchmark runs against a configured real deployment

- **WHEN** the benchmark runs its workload against a configured real deployment
- **THEN** the writing/updating process and the reading process run concurrently as independent processes, the workload stays within the declared throughput and storage envelope, and the benchmark completes in under 20 seconds

### Requirement: The benchmark proves the cache's benefit over direct, uncached access

The benchmark SHALL measure the reading workload's performance once through the cache and once through direct, uncached access to the same real deployment, using the same operations and data shape for both, in the same run. It SHALL fail if the cached measurement is not at least twice as fast as the direct, uncached measurement.

#### Scenario: The cached and direct phases both complete

- **WHEN** the benchmark measures the cached reading workload and the direct, uncached reading workload against the same real deployment in the same run
- **THEN** the benchmark fails unless the cached measurement is at least twice as fast as the direct, uncached measurement

### Requirement: The benchmark guards against absolute performance and resource regressions

The benchmark SHALL assert that its measured wall-clock time and its measured count of server round trips each stay within a fixed ceiling recorded from an initial run against the real deployment. The wall-clock ceiling SHALL carry enough margin above that initial measurement to tolerate ordinary shared-deployment variance without masking a material regression; the round-trip ceiling, being deterministic and independent of deployment variance, SHALL match the initial measurement exactly.

#### Scenario: A change makes either measured phase materially slower or chattier

- **WHEN** the benchmark's measured wall-clock time or measured count of server round trips for either phase exceeds its recorded ceiling
- **THEN** the benchmark fails and identifies which measurement exceeded its ceiling
