## Purpose

This capability verifies that the versioned public distribution can be built and consumed without granting a workflow authority to publish it.

## ADDED Requirements

### Requirement: Release artifacts are validated before publication
The repository SHALL build source and wheel distributions, install the wheel into an isolated environment, import the documented synchronous and asyncio public surfaces, and verify package-version consistency before a release is considered verified.

#### Scenario: A wheel omits a public module
- **WHEN** the isolated wheel-install validation cannot import a documented public module
- **THEN** the release-verification command fails

### Requirement: Release verification does not publish
The release workflow SHALL validate artifacts without uploading packages, using publishing credentials, or assuming registry ownership. A future publishing workflow SHALL require a separately approved change.

#### Scenario: Release verification completes
- **WHEN** the non-publishing release command completes successfully
- **THEN** it leaves no package published or external release state changed
