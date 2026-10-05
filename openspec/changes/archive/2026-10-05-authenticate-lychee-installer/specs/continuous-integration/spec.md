## ADDED Requirements

### Requirement: Lychee installation uses scoped read-only authentication

The pull request quality gate SHALL authenticate Lychee's GitHub release installation using the read-only job token, scoped to the Lychee hook invocation. Other hook invocations SHALL not receive that token through the environment. Link validation SHALL remain required regardless of installation or result-cache availability, and installation or link-check failures SHALL fail the gate.

#### Scenario: The hook installation cache is absent

- **WHEN** a pull request runner needs to install the pinned Lychee release
- **THEN** the release installer receives the read-only job token and the hook checks the selected files after installation

#### Scenario: A fork pull request needs installation

- **WHEN** a fork pull request runs the quality gate without a cached Lychee binary
- **THEN** the installer uses the automatic read-only job token without requiring a custom repository secret

#### Scenario: Validation fails

- **WHEN** Lychee installation or link validation fails
- **THEN** the Prek quality gate fails and its dependent expensive jobs do not start

#### Scenario: Other hooks run

- **WHEN** the quality gate invokes the other Prek hooks
- **THEN** their environment does not contain the token supplied to the Lychee installer
