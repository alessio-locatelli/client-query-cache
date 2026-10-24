## ADDED Requirements

### Requirement: Pull requests enforce native coverage after static checks

Pull requests affecting native implementation, native coverage tooling, or tests and dependencies used by native coverage SHALL run the native production coverage gate after native static checks pass. Interpreter-independent native coverage SHALL run once per pull request, separately from the Python compatibility matrix. Failed thresholds or measurement errors SHALL fail validation.

#### Scenario: Native coverage inputs change

- **WHEN** a pull request changes a native implementation or coverage input and static validation passes
- **THEN** the native coverage command runs and determines the CI check outcome

#### Scenario: The threshold is not met

- **WHEN** native production coverage falls below the required threshold
- **THEN** the check fails rather than lowering the threshold or becoming informational
