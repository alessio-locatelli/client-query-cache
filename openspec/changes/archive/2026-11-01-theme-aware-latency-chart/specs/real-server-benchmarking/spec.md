## ADDED Requirements

### Requirement: The benchmark logs median read latency per phase

The benchmark SHALL log the median latency of its measured cached and uncached reads.

#### Scenario: A maintainer reads the benchmark log

- **WHEN** the benchmark completes both reader phases
- **THEN** its log records the median cached and direct read latency
