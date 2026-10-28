# release-verification Specification

## Purpose

This capability verifies that the versioned public distribution can be built and consumed without granting a workflow authority to publish it.

## Requirements

### Requirement: Release artifacts are validated before publication

The repository SHALL build source and wheel distributions, install each artifact into its own isolated environment on each supported architecture, import the documented synchronous and asyncio public surfaces from each installation, and verify package-version consistency before a release is considered verified. Wheel verification SHALL use matching native hardware. Publication SHALL require successful verification of every supported architecture for the release revision.

#### Scenario: A wheel omits a public module

- **WHEN** the isolated wheel-install validation cannot import a documented public module
- **THEN** the release-verification command fails

#### Scenario: An sdist omits a public module

- **WHEN** the isolated sdist-install validation cannot import a documented public module
- **THEN** the release-verification command fails

#### Scenario: An architecture has no successful verification

- **WHEN** a supported architecture's release verification fails, is cancelled or is unavailable
- **THEN** the release is not verified and publication does not proceed with only the other architecture's artifacts

### Requirement: Release verification does not publish

The release workflow SHALL validate artifacts without uploading packages, using publishing credentials, or assuming registry ownership. A future publishing workflow SHALL require a separately approved change.

#### Scenario: Release verification completes

- **WHEN** the non-publishing release command completes successfully
- **THEN** it leaves no package published or external release state changed
