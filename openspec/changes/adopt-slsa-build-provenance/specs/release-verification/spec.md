# Spec Delta

## MODIFIED Requirements

### Requirement: Release verification does not publish

The release workflow SHALL validate artifacts without uploading packages, creating provenance attestations, using publishing credentials, or assuming registry ownership.

#### Scenario: Release verification completes

- **WHEN** the non-publishing release command completes successfully
- **THEN** it leaves no package published or external release state changed

#### Scenario: Release verification builds distributions

- **WHEN** the non-publishing release workflow builds and uploads its inspection artifacts
- **THEN** no provenance attestation exists for them, so they cannot pass the documented release provenance verification
