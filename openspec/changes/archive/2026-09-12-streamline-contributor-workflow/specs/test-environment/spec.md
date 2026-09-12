## MODIFIED Requirements

### Requirement: Production branch coverage cannot regress

The repository SHALL measure branches for every importable production module and SHALL rely on the
configured covdefaults policy rather than an individual command invocation to enforce its coverage
threshold. The coverage command SHALL execute the current test suite once under coverage and fail
when the report falls below that enforced threshold. The repository SHALL NOT exclude ordinary
production paths from measurement.

#### Scenario: A reachable branch is not covered

- **WHEN** a coverage run leaves a production branch unexecuted
- **THEN** the report identifies the missing branch and the command fails if coverage falls below the
  configured threshold

#### Scenario: A contributor runs the coverage command

- **WHEN** a contributor runs the documented coverage command with an accessible container runtime
- **THEN** unit, integration, and end-to-end tests execute in one pytest invocation and the coverage
  report is produced from that run

#### Scenario: Planned behavior remains unimplemented

- **WHEN** the baseline includes a production branch owned by `implement-change-stream-coherency`
- **THEN** the branch remains visible as missing coverage without a coverage exclusion
