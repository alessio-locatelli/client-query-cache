## Purpose

Provide a reproducible benchmark protocol that measures when consolidated
change-stream caching helps a defined MongoDB workload and when it does not.

## ADDED Requirements

### Requirement: Comparable workload variants
The benchmark suite SHALL run equivalent raw-read and warm-cache workload
variants against the same seeded replica-set dataset, read consistency profile,
query shapes, document sizes, operation mix, client concurrency, and duration.
It SHALL include idle-stream, read-heavy/write-light, balanced, and
write-dominant scenarios.

#### Scenario: Raw and cached comparison
- **WHEN** a benchmark compares raw reads with warm cached reads
- **THEN** its report identifies the identical workload parameters and the
  measured difference in read count, latency, client CPU, and byte metrics

### Requirement: Change-stream topology coverage
The benchmark suite SHALL measure one database-scoped stream serving multiple
cached collections and SHALL vary the rate of relevant and unrelated database
writes. It SHALL report the stream scope and number of cached collections so a
result cannot be mistaken for a per-document-watcher measurement.

#### Scenario: Unrelated database activity
- **WHEN** writes occur in a namespace with no resident document entry
- **THEN** the report shows observed events and derived-result invalidations
  separately from document-cache evictions

### Requirement: Measured cost dimensions
Each benchmark result SHALL record latency distribution, client wall and CPU
time, logical stream-event bytes, cache counters, and replica-set container CPU
time when run in the controlled local topology. An optional dedicated
unencrypted, uncompressed TCP-proxy mode SHALL report bidirectional bytes and
identify them as measurements of that proxy topology only.

#### Scenario: Default benchmark result
- **WHEN** a benchmark run completes without the optional proxy
- **THEN** the report includes logical activity and CPU measurements but does
  not claim to measure wire bytes

#### Scenario: Proxy benchmark result
- **WHEN** a benchmark run uses the dedicated proxy topology with transport
  encryption and compression disabled
- **THEN** the report records proxy-observed bytes and labels the result with
  those transport conditions

### Requirement: Reproducible, versioned reports
The benchmark command SHALL emit a versioned machine-readable report containing
the library revision, Python and PyMongo versions, MongoDB image/version,
hardware and container limits, workload parameters, transport settings, warmup,
sample count, and measured values. It SHALL fail rather than silently report a
partial run when required topology or measurement sources are unavailable.

#### Scenario: Missing controlled topology
- **WHEN** a benchmark requiring replica-set or container CPU measurement
  cannot reach that topology
- **THEN** the command fails with the missing prerequisite and does not produce
  a report presented as a complete comparison

### Requirement: Evidence-based guidance
Published benchmark guidance SHALL link each stated result to its versioned
report and SHALL describe the tested workload. It SHALL NOT claim a universal
byte, CPU, latency, or read/write-ratio break-even threshold.

#### Scenario: Workload-specific conclusion
- **WHEN** a report shows a benefit for a read-heavy scenario
- **THEN** its documentation identifies that scenario's document sizes, read and
  write rates, concurrency, stream topology, and measurement limits
