# Release Publishing Specification

## Purpose

This capability lets a maintainer turn a reviewed set of merged changes into a versioned, changelogged GitHub Release whose build artifacts are published to PyPI without a stored long-lived credential.

## Requirements

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

### Requirement: A release tag identifies a single, matching package version

A release SHALL be identified by a `vX.Y.Z` Git tag, and the tagged commit's package version SHALL match the tag with its `v` prefix stripped.

#### Scenario: A maintainer cuts a release

- **WHEN** a maintainer pushes a `vX.Y.Z` tag
- **THEN** the tagged commit's package version is `X.Y.Z`

### Requirement: Publishing reuses release verification and blocks on failure

The publish workflow SHALL build the source and wheel distributions and verify them using the repository's non-publishing release-verification command before any publish step runs. A verification failure SHALL prevent publishing.

#### Scenario: A tagged commit fails release verification

- **WHEN** the release-verification command fails for a pushed release tag
- **THEN** the publish workflow fails before any package is uploaded

### Requirement: Publishing requires no stored credential and a manual approval

The publish workflow SHALL trigger only on a pushed `vX.Y.Z` tag, SHALL authenticate to PyPI using OpenID Connect trusted publishing without a stored API token, and SHALL run its upload step only inside a protected environment that requires manual reviewer approval.

#### Scenario: A release tag is pushed

- **WHEN** a `vX.Y.Z` tag is pushed and release verification succeeds
- **THEN** the workflow pauses for required-reviewer approval before the upload step runs, and no PyPI API token is read from a repository secret

#### Scenario: A reviewer approves the pending publish

- **WHEN** a required reviewer approves the pending deployment
- **THEN** the workflow uploads the verified artifacts to PyPI using a short-lived OpenID Connect token

### Requirement: Each publish creates a matching GitHub Release from the changelog

Publishing a version SHALL create a GitHub Release for that tag whose notes are the tagged version's `CHANGELOG.md` section.

#### Scenario: A publish completes

- **WHEN** the publish workflow uploads a version to PyPI
- **THEN** a GitHub Release exists for that tag with a body equal to that version's `CHANGELOG.md` section

### Requirement: The release workflow is documented for maintainers

`CONTRIBUTING.md` SHALL document how to maintain the changelog, bump the version, and create a release tag. The project's documentation SHALL also document the one-time PyPI trusted-publisher and environment-reviewer setup required before the first release, linked from `CONTRIBUTING.md`'s release section.

#### Scenario: A maintainer cuts a release

- **WHEN** a maintainer follows the documented release section
- **THEN** they can identify every per-release step needed to publish successfully

#### Scenario: A maintainer prepares the first release

- **WHEN** a maintainer follows the documented release section before any release has been published
- **THEN** they can find the one-time PyPI trusted-publisher and environment-reviewer setup steps and every value to enter
