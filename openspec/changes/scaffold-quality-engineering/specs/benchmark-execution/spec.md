## Purpose

Contributors need repeatable benchmark commands and artifacts without treating measurements from one machine as universal performance guarantees.

## ADDED Requirements

### Requirement: Benchmarks are opt-in and reportable
The repository SHALL provide an opt-in benchmark command that produces pytest-benchmark-compatible result data and SHALL keep benchmark sampling out of the default unit and coverage commands. Benchmark output SHALL identify the revision, interpreter, dependency environment, and invocation parameters needed to interpret or compare the result.

#### Scenario: A contributor runs routine tests
- **WHEN** a contributor runs the documented default test or coverage command
- **THEN** benchmark sampling does not run

#### Scenario: A contributor requests benchmarks
- **WHEN** a contributor runs the documented benchmark command
- **THEN** the command executes the selected benchmarks and writes a result artifact with the required execution metadata

### Requirement: Benchmarks do not enforce host-dependent regressions
Continuous integration SHALL preserve requested benchmark reports as artifacts when benchmark execution is explicitly selected, but SHALL not pass or fail a normal change based on timing differences across hosted runners. The specialized stream-cost workload and measurement contract SHALL remain compatible with this generic benchmark substrate.

#### Scenario: A manually selected benchmark job completes
- **WHEN** a benchmark workflow is manually selected in continuous integration
- **THEN** it uploads its benchmark report and does not apply an uncalibrated cross-run timing threshold
