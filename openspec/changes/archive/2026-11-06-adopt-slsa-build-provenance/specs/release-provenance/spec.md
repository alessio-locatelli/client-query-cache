# Spec Delta

## Purpose

This capability gives users signed, publicly verifiable SLSA build provenance for every published distribution, so they can confirm that it was built by this repository's publishing workflow from a release tag.

## ADDED Requirements

### Requirement: Every published distribution has SLSA Build Level 2 provenance

Each release SHALL produce signed SLSA Build Level 2 provenance for the source distribution and every wheel it publishes. The provenance SHALL identify each file by SHA-256 digest. It SHALL record the release tag, its commit, the publishing workflow and the signing job's runner environment. Anyone SHALL be able to retrieve and verify it without a credential issued by the project.

#### Scenario: A release is published

- **WHEN** a `vX.Y.Z` release completes publication
- **THEN** the source distribution and each architecture's wheel have provenance that names that tag, its commit and the publishing workflow, and its signature is recorded in a public transparency log

#### Scenario: A published file is altered

- **WHEN** a user verifies a file whose content differs from a published distribution
- **THEN** no provenance matches its digest and verification fails

### Requirement: Release builds run on GitHub-hosted runners

Every publishing-workflow job that builds or signs a distribution SHALL run on a GitHub-hosted runner, as declared in the workflow definition at the commit that the provenance names.

#### Scenario: A consumer audits a verified release

- **WHEN** a consumer inspects the publishing workflow at the commit named by a release's provenance
- **THEN** every job that builds or signs that release's distributions declares a GitHub-hosted runner

### Requirement: Provenance signing is isolated from build steps

A job that checks out the repository, installs project dependencies, or builds or tests distributions SHALL NOT be able to obtain a provenance-signing identity. Signing SHALL happen in a job whose only inputs are the built distributions and whose only commands sign them and cryptographically verify the resulting provenance.

#### Scenario: A build-time dependency is compromised

- **WHEN** code that runs during the release build tries to sign provenance for an arbitrary file
- **THEN** no signing identity is available to that job, and the only provenance for the release comes from the dedicated signing job

### Requirement: Publication requires verifiable provenance

Before any distribution is uploaded and before the GitHub Release is created, every distribution SHALL pass verification under the policy documented for users. The policy requires this repository, the publishing workflow as signer, the release tag as source ref, and a GitHub-hosted signing runner. A failed signing or verification step SHALL stop the release.

#### Scenario: Provenance cannot be signed or verified

- **WHEN** signing fails, or any distribution fails the documented verification policy
- **THEN** the workflow fails before the GitHub Release draft and the PyPI approval gate, and nothing is uploaded

#### Scenario: Every distribution verifies

- **WHEN** every distribution passes the documented verification policy
- **THEN** the release continues to the GitHub Release draft and the PyPI approval gate

### Requirement: Release tags are never reused

The release procedure SHALL NOT delete or recreate a pushed release tag at another commit. A release that cannot complete SHALL continue under a new version. This procedural rule, not verification, keeps one commit per tag, because verification checks the tag name rather than the commit.

#### Scenario: A release fails or is rejected

- **WHEN** a release needs a fix or is rejected at any point after its tag was pushed
- **THEN** its tag keeps pointing at the original commit, and the fix is released under the next version

#### Scenario: An earlier run is re-run after a fix

- **WHEN** a failed run of a release tag is re-run later
- **THEN** it signs the commit it originally built, and no other commit has provenance under that tag
