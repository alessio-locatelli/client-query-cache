## MODIFIED Requirements

### Requirement: The repository maintains a version-keyed changelog

`CHANGELOG.md` SHALL contain an "Unreleased" section for merged changes not yet published and one dated `[X.Y.Z] - YYYY-MM-DD` section per published release. Entry eligibility and wording SHALL follow the editing policy in root `CHANGELOG.md`'s opening HTML comment.

#### Scenario: A release is cut

- **WHEN** a maintainer prepares a new release
- **THEN** the "Unreleased" section is renamed to the new version and date, and a new empty "Unreleased" section is opened above it

#### Scenario: A package behavior bug is fixed

- **WHEN** a merged change fixes a bug in the package's public behavior and qualifies under the changelog editing policy
- **THEN** its entry is added under "Unreleased"

#### Scenario: Only documentation publication changes

- **WHEN** a merged change affects only documentation-publication infrastructure
- **THEN** no package changelog entry is added
