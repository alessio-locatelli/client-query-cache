## ADDED Requirements

### Requirement: Pull requests enforce native quality checks

Pull requests affecting native source, native tool selection, native policy, or shared validation commands SHALL run native static checks before native unit tests and concurrency models. Native checks independent of the Python interpreter SHALL run once per pull request rather than once per Python compatibility lane. Failures SHALL remain visible as failed checks.

#### Scenario: A native source file changes

- **WHEN** a pull request changes native source
- **THEN** static validation gates native unit tests and model execution

#### Scenario: A native tool or policy changes

- **WHEN** a pull request changes native tool setup or dependency policy
- **THEN** the corresponding native consumer checks run
