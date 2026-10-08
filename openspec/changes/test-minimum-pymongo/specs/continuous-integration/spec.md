# Continuous Integration Spec Delta

## ADDED Requirements

### Requirement: Pull requests validate the declared PyMongo minimum

PRs selected for Python validation, including minimum-driver environment configuration changes, SHALL run the development-environment specification's minimum-PyMongo check after applicable quality gates. CI SHALL run it once on the development interpreter alongside existing locked-driver lanes. Failed, cancelled, or unexpectedly skipped minimum validation SHALL fail the existing stable compatibility gate. Unrelated documentation-only PRs SHALL not start it.

#### Scenario: A newer locked driver passes

- **WHEN** locked-driver tests pass but the declared-minimum check fails
- **THEN** the stable compatibility gate fails and prevents acceptance

#### Scenario: Minimum-driver configuration changes

- **WHEN** a PR changes the minimum-driver environment configuration without editing Python source
- **THEN** CI selects Python validation and runs the minimum-driver check

#### Scenario: Validation cannot complete

- **WHEN** minimum-driver setup fails, the job is cancelled, or it is unexpectedly skipped while Python validation applies
- **THEN** the stable compatibility gate reports failure

#### Scenario: Quality validation fails

- **WHEN** a required linting or formatting prerequisite fails
- **THEN** the minimum-driver workload does not start and the failed prerequisite blocks acceptance

#### Scenario: Only unrelated documentation changes

- **WHEN** a PR changes no Python-validation input
- **THEN** CI does not start minimum-driver validation
