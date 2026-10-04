# Spec Delta

## ADDED Requirements

### Requirement: Pull requests run an isolated memory gate

Pull requests selected by the existing Python-validation path scope SHALL run the memory command in a dedicated Linux job using the locked dependencies and repository interpreter. The job SHALL wait for applicable quality checks, require no MongoDB, and fail on memory assertions or profiling errors. Unrelated documentation-only changes SHALL not start it. Cached results SHALL not determine thresholds.

#### Scenario: Python validation is selected

- **WHEN** Python source, pytest configuration, dependency metadata, lockfile, interpreter, test recipe, validation workflow, or shared toolchain setup changes and quality checks pass
- **THEN** a separate memory job runs the dedicated command on the selected revision

#### Scenario: Quality checks fail

- **WHEN** a required linting or formatting check fails
- **THEN** the memory workload does not start

#### Scenario: An unrelated document changes

- **WHEN** a pull request changes only documentation outside the Python-validation scope
- **THEN** no memory workload runs

### Requirement: Memory failures preserve safe diagnostics

The memory job SHALL retain allocation traces and useful failure output for seven days on failure. Diagnostics SHALL contain only synthetic workload data and SHALL remain untracked. Documentation SHALL identify the reproduction command, workload, measured scope, calibrated ceilings, and runtime overhead.

#### Scenario: A ceiling is exceeded

- **WHEN** the memory command fails after producing an allocation trace
- **THEN** CI exposes the failure output and uploads the trace with seven-day retention

#### Scenario: Profiling fails before producing a trace

- **WHEN** dependency loading or profiling fails before a trace exists
- **THEN** the job remains failed and the original error remains visible
