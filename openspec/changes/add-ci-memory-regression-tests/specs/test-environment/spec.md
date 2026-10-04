# Spec Delta

## ADDED Requirements

### Requirement: Memory profiling has an explicit execution tier

The repository SHALL provide an opt-in memory test command isolated from ordinary unit, integration, end-to-end, coverage, and latency benchmark runs. The command SHALL profile only memory tests without requiring MongoDB. Missing profiling support, disabled instrumentation, or zero selected memory tests SHALL fail visibly.

#### Scenario: A contributor runs ordinary validation

- **WHEN** a contributor runs a provided correctness, coverage, or latency benchmark command
- **THEN** memory tests are excluded and allocation profiling is not enabled

#### Scenario: A contributor runs memory validation

- **WHEN** a contributor runs the dedicated memory command on the supported Linux toolchain
- **THEN** only the memory tier is profiled, without a database or container runtime

#### Scenario: Memory instrumentation is unavailable

- **WHEN** memory tests are explicitly selected without active allocation instrumentation or the command selects no tests
- **THEN** the command fails visibly rather than reporting an unmeasured success

### Requirement: Memory regression workload exercises bounded cache reclamation

Memory tests SHALL exercise repeated admissions, hits, eviction, invalidation, and namespace clearing at fixed namespace cardinality with a shared 4 MiB BSON budget. Identity entries with aliases and namespace-guarded entries SHALL be covered. Tests SHALL fail on declined expected admissions, absent expected hits or eviction, budget overflow, retained reclaimed metadata, or nonzero entry usage after clearing and closing.

#### Scenario: Workload exceeds cache capacity repeatedly

- **WHEN** each admission mode processes eight cycles of 1,024 fresh documents with 64 KiB payloads across two fixed namespaces, including writes and readmission
- **THEN** admissions and hits succeed, evictions occur, BSON usage stays within budget, and entry indexes, identities, and aliases reference only resident entries at quiescent checkpoints

#### Scenario: Namespace contents are reclaimed

- **WHEN** each workload cycle clears both namespaces with no in-flight admissions
- **THEN** entry count and BSON usage are zero and both namespaces have no entry-index tokens, identity records, or aliases

#### Scenario: The core closes after workload completion

- **WHEN** the workload's core is closed
- **THEN** entry count and BSON usage are zero

### Requirement: Memory ceilings are measured and regression-sensitive

Each memory case SHALL enforce a committed peak-allocation ceiling, calibrated from repeated fresh-process measurements on the CI toolchain. Its ceiling SHALL be the whole-MiB rounding of 1.5 times the largest of ten baseline peaks and SHALL not exceed 32 MiB. Exceeding it SHALL fail. Calibration SHALL demonstrate that retaining all admitted encoded values fails the memory ceiling independently of structural assertions.

#### Scenario: Healthy workload establishes a ceiling

- **WHEN** ten independent baseline runs complete for each case
- **THEN** the documented ceiling follows the calibration rule, is at most 32 MiB, and all baseline runs pass it

#### Scenario: Encoded values accumulate outside budget accounting

- **WHEN** a temporary fault retains every admitted encoded value while normal eviction and reclamation accounting continue
- **THEN** the profiled workload fails its peak-allocation ceiling

#### Scenario: Baseline requires an excessive ceiling

- **WHEN** calibration would require a ceiling above 32 MiB
- **THEN** implementation stops for investigation rather than silently widening the guard
