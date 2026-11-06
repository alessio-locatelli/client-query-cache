# Proposal

## Why

Users cannot currently check how a published `client-query-cache` distribution was built. Adopting [SLSA](https://slsa.dev/) Build Level 2 gives them verifiable evidence that each release was built by this repository's publishing workflow from the release tag. Advertising that level in the README shows users that the project takes quality and supply-chain security seriously. The claim is backed by enforced automation, not just a badge.

## What Changes

- Every release publishes signed SLSA build provenance for its source distribution and wheels, and stops before publication if that provenance does not verify.
- The release procedure never moves a release tag once provenance signing has started for it.
- Users get a guide for verifying downloaded distributions. Once the first release with provenance is published, the README shows an SLSA Build Level 2 badge that links to that guide ([issue #420](https://github.com/alessio-locatelli/client-query-cache/issues/420)).

## Capabilities

### New Capabilities

- `release-provenance`: provenance guarantees for published distributions.

### Modified Capabilities

- `release-verification`: the non-publishing boundary now also excludes provenance. The obsolete sentence that anticipates a future publishing workflow is dropped.
- `public-library-documentation`: adds the SLSA badge and the provenance verification guide.

## Impact

- `.github/workflows/publish.yml` and a new pinned action dependency.
- `README.md`, `docs/user/getting-started/installation.md`, `.github/SECURITY.md`, `CONTRIBUTING.md`.
