# Spec Delta

## ADDED Requirements

### Requirement: Parallel test failures retain worker diagnostics

The existing database-backed CI job SHALL retain controller and worker log files in its failure artifact for seven days. Missing log files SHALL not replace or hide the original test failure.

#### Scenario: A parallel test fails

- **WHEN** the database-backed coverage command fails after workers produce logs
- **THEN** the existing diagnostic artifact contains controller and worker files with seven-day retention

#### Scenario: Failure precedes worker logging

- **WHEN** the command fails before worker log files exist
- **THEN** CI reports the original command failure without requiring absent log files
