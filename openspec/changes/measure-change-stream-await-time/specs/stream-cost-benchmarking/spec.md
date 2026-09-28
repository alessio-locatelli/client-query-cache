# Spec Delta

## ADDED Requirements

### Requirement: Await-time candidates are measured on matched stream workloads

The benchmark SHALL compare the existing 1,000 ms value with multiple larger candidate `max_await_time_ms` values on the same supported MongoDB topology, using a genuine idle window and relevant-write windows with equivalent data, event schedules, warmup, resource limits, and stream count. Runs SHALL be repeated with counterbalanced candidate order and fresh cache and stream state. It SHALL record actual `getMore` command counts and requested `maxTimeMS` values, MongoDB-container and benchmark-process CPU, direct-path bytes, event counts, write-to-invalidation latency, and manager shutdown duration for both synchronous and asynchronous paths. A missing or unmatched measure SHALL invalidate that comparison. The report SHALL distinguish values observed on a replica set from any unmeasured sharded-cluster behavior.

#### Scenario: An idle candidate is measured

- **WHEN** the benchmark samples a candidate during a window with no application reads or writes
- **THEN** its report contains actual `getMore` counts and resource measures for that window, with no operation-latency samples

#### Scenario: Candidate workloads differ

- **WHEN** candidate runs differ in event schedule, stream count, topology, or measurement scope
- **THEN** report validation rejects their comparison as evidence for a default

#### Scenario: A worker-loop count substitutes for wire commands

- **WHEN** a report uses the manager's `stream_polls` counter as its count of actual `getMore` commands
- **THEN** report validation rejects that count

### Requirement: Await-time guidance follows a pre-registered decision rule

Before sampling, the benchmark SHALL freeze a versioned configuration with candidate values, workloads, repetitions, durations, write schedules, metrics, confidence-interval method, multiplicity adjustment, acceptable latency and shutdown limits, treatment of measurement noise, and the rule for selecting one default. The report SHALL identify that exact configuration by content hash and retain the per-candidate decision evidence, including failed and inconclusive comparisons, with the repository revision and environment. The selected default SHALL pass the registered invalidation-lag, active server and client CPU, idle client CPU, and shutdown limits, then show a decisive idle server CPU or direct-path-byte reduction in both execution models. Among eligible values, the ranking SHALL use the worse resource result across synchronous and asynchronous paths, prefer a decisively lower idle server CPU in both, then decisively lower direct-path bytes in both, then the shorter wait when differences remain unresolved. A claimed improvement SHALL account for all registered candidate and workload comparisons; an apparent saving within adjusted measurement uncertainty SHALL not justify changing the 1,000 ms default. Public guidance SHALL name the selected value, link the retained evidence, describe its resource and responsiveness trade-offs, and state the topology and timeout limitations. It SHALL not claim an unmeasured universal optimum.

#### Scenario: A larger value meets the rule

- **WHEN** repeated measurements show a candidate's resource benefit beyond the registered noise threshold while its latency and shutdown results meet the registered limits
- **THEN** the decision evidence selects the qualifying candidate with the lowest measured resource cost according to the registered ranking rule

#### Scenario: Results are inconclusive

- **WHEN** candidates cannot be distinguished reliably or all larger values violate the registered limits
- **THEN** the decision evidence retains 1,000 ms, labels the result accordingly, and makes no claim of a measured improvement

#### Scenario: A rule is chosen after sampling

- **WHEN** a report uses thresholds or candidate-ranking criteria not fixed before sampling
- **THEN** it cannot support a new default recommendation
