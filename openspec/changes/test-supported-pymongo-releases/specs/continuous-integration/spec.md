# Continuous Integration Spec Delta

## ADDED Requirements

### Requirement: Pull requests validate supported PyMongo releases

PRs selected for Python validation SHALL run the development-environment specification's release check once, in the minimum-driver job on the development interpreter, after the minimum check succeeds. Failed, cancelled, or unexpectedly skipped release validation SHALL fail the existing stable compatibility gate. CI SHALL NOT start a job or matrix entry per release.

#### Scenario: A release in range fails

- **WHEN** locked-driver tests and the minimum check pass but the behavioral tests fail on another supported release
- **THEN** the stable compatibility gate fails and prevents acceptance

#### Scenario: The minimum check fails

- **WHEN** the minimum check fails
- **THEN** the release check does not start and the stable compatibility gate fails

#### Scenario: The release range grows

- **WHEN** the package index lists additional in-range releases
- **THEN** the same job tests them sequentially and the set of CI jobs is unchanged

#### Scenario: A release fails in CI

- **WHEN** the behavioral tests fail on a release in CI
- **THEN** the job uploads the release runs' diagnostic logs as an artifact
