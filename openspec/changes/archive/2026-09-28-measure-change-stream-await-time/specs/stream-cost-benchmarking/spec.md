# Spec Delta

## ADDED Requirements

### Requirement: Await-time candidates use matched workload windows

The benchmark SHALL compare 1,000 ms with multiple larger await times under matched idle and relevant-write workloads, repeated in counterbalanced order with fresh state.

#### Scenario: An idle candidate is measured

- **WHEN** the benchmark samples a candidate during a window with no application reads or writes
- **THEN** its report contains actual `getMore` counts and resource measures for that window, with no operation-latency samples

#### Scenario: Candidate workloads differ

- **WHEN** candidate runs differ in event schedule, stream count, topology, or measurement scope
- **THEN** report validation rejects their comparison as evidence for a default

### Requirement: Await-time reports record wire commands and costs

The benchmark SHALL record actual `getMore` counts and requested `maxTimeMS`, server and client CPU, direct bytes, event counts, invalidation lag, and shutdown duration for both execution models.

#### Scenario: A worker-loop count substitutes for wire commands

- **WHEN** a report uses the manager's `stream_polls` counter as its count of actual `getMore` commands
- **THEN** report validation rejects that count

#### Scenario: A required measure is missing

- **WHEN** a candidate lacks a required matched wire, CPU, byte, event, lag, or shutdown measure
- **THEN** report validation rejects that candidate comparison

### Requirement: Await-time reports state topology scope

The report SHALL distinguish measurements on the tested replica set from unmeasured sharded-cluster behavior.

#### Scenario: A report generalizes beyond its topology

- **WHEN** results measured on a replica set are described as covering sharded clusters
- **THEN** report validation rejects that unsupported claim

### Requirement: Await-time decisions use a frozen configuration

The benchmark SHALL freeze candidate workloads, metrics, uncertainty rules, limits, and selection criteria before sampling and retain the configuration hash with results.

#### Scenario: A rule is chosen after sampling

- **WHEN** a report uses thresholds or candidate-ranking criteria not fixed before sampling
- **THEN** it cannot support a new default recommendation

#### Scenario: A frozen configuration omits decision inputs

- **WHEN** the pre-run configuration lacks candidate values, repetitions, durations, write schedules, confidence-interval method, multiplicity adjustment, noise treatment, or latency and shutdown limits
- **THEN** the report cannot use that configuration to justify a selected default

### Requirement: Await-time defaults meet registered limits

A selected await-time default SHALL meet registered lag, active server and client CPU, idle client CPU, and shutdown limits, then show decisive idle server CPU or direct-byte savings in both execution models.

#### Scenario: A larger value meets the rule

- **WHEN** repeated measurements show a candidate's resource benefit beyond the registered noise threshold while its latency and shutdown results meet the registered limits
- **THEN** the decision evidence selects the qualifying candidate with the lowest measured resource cost according to the registered ranking rule

### Requirement: Await-time candidates follow the registered ranking

Eligible candidates SHALL be ranked by their worse resource result across sync and asyncio paths: decisive idle server CPU reduction in both paths first, then decisive direct-byte reduction in both, then the shorter wait when unresolved.

#### Scenario: Two eligible candidates offer different resource savings

- **WHEN** candidate outcomes satisfy the registered safety limits
- **THEN** the decision applies the CPU, byte, and shorter-wait tie-breaks in that order across both execution models

### Requirement: Await-time evidence retains every candidate outcome

The report SHALL retain each candidate's decision evidence, including failed and inconclusive comparisons, together with the configuration hash, repository revision, and environment.

#### Scenario: A candidate does not qualify

- **WHEN** a candidate fails a registered limit or its improvement is inconclusive after adjustment for all candidate and workload comparisons
- **THEN** its evidence remains in the report and cannot be omitted from the decision

#### Scenario: Commit reproducible evidence as a summary

- **WHEN** benchmark evidence is added to source control
- **THEN** a prose Markdown summary records every candidate outcome, failures, limitations, configuration hash, revision, environment, and reproduction commands
- **AND** raw results remain untracked, with only a genuinely useful reproduction configuration under 200 lines retained as JSON

### Requirement: Inconclusive await-time comparisons retain the default

Measurement noise SHALL NOT justify changing the 1,000 ms default; public guidance SHALL state the evidence and limitations.

#### Scenario: Results are inconclusive

- **WHEN** candidates cannot be distinguished reliably or all larger values violate the registered limits
- **THEN** the decision evidence retains 1,000 ms, labels the result accordingly, and makes no claim of a measured improvement

### Requirement: Public await-time guidance cites the selected evidence

Public guidance SHALL name the selected value, link retained evidence, explain resource and responsiveness trade-offs, and state topology and PyMongo timeout limits without claiming an unmeasured universal optimum.

#### Scenario: A default is published

- **WHEN** the library documents its chosen `max_await_time_ms`
- **THEN** readers can find the measured rationale, committed summary, trade-offs, and the limits of the tested environment
