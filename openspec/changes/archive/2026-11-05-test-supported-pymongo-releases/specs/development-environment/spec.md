# Development Environment Spec Delta

## ADDED Requirements

### Requirement: Supported PyMongo releases are exercised

The contributor workflow SHALL exercise every non-yanked, non-pre-release PyMongo release that satisfies the published dependency specifier, except the declared minimum and the locked release, which other checks cover. Each release SHALL run the minimum check's behavioral tests against disposable MongoDB without changing committed dependency metadata or the lockfile.

#### Scenario: A release appears between lockfile updates

- **WHEN** the package index lists a release inside the declared range that is neither the declared minimum nor the locked release
- **THEN** the next validation run tests that release with the minimum check's behavioral tests

#### Scenario: A release fails the behavioral tests

- **WHEN** the behavioral tests fail on one release
- **THEN** validation fails visibly, identifies that release, and does not substitute another driver version

#### Scenario: Published metadata excludes a release

- **WHEN** published dependency metadata excludes a release because it is defective
- **THEN** validation does not test that release

#### Scenario: A release is yanked or a pre-release

- **WHEN** the package index marks a release yanked or the release is a pre-release
- **THEN** validation does not test it

#### Scenario: No other release is in range

- **WHEN** the only releases inside the declared range are the declared minimum and the locked release
- **THEN** the release check tests nothing further and succeeds

### Requirement: The release list comes from the package index at run time

Release validation SHALL query the package index for the release list on every run instead of reading a hand-maintained list. When the index cannot be queried, returns an unusable response, or lacks the declared minimum, validation SHALL fail visibly instead of testing no releases.

#### Scenario: The package index is unreachable

- **WHEN** the package index cannot be queried during release validation
- **THEN** the contributor command fails with an error naming the failed query and tests no release

#### Scenario: The listing is empty or truncated

- **WHEN** the index response is well-formed but does not list the declared minimum
- **THEN** the contributor command fails visibly instead of treating the range as having no other release
