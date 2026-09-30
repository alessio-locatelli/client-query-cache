# Proposal

## Why

`client-query-cache` has never been tagged, released, or published: `pyproject.toml` carries a
static `version = "0.1.0"`, no `CHANGELOG.md` exists, and the in-flight `add-release-verification`
change deliberately stops at proving artifacts install and import correctly, without tagging,
publishing, or touching credentials. Once that verification exists, the project still has no
documented or automated path from a reviewed change to an installable PyPI release.

## What Changes

- Add a manually maintained `CHANGELOG.md` with an "Unreleased" section that contributors update
  as part of each change, matching the convention `AGENTS.md` already assumes.
- Add a tag-triggered `.github/workflows/publish.yml` workflow that reuses
  `add-release-verification`'s non-publishing build and isolated-install/import check, then
  publishes the verified sdist and wheel to PyPI via Trusted Publishing (OIDC) from a protected
  `pypi` GitHub Environment that requires manual reviewer approval before the upload step runs.
- Add a GitHub Release creation step, sourcing its release notes from the tagged version's
  `CHANGELOG.md` section instead of duplicating them by hand or auto-generating them from commits.
- Document the end-to-end release workflow in `CONTRIBUTING.md`: maintaining the changelog,
  bumping the version, creating the tag, and the one-time PyPI trusted-publisher registration the
  maintainer must complete outside this repository before the first release.

## Capabilities

### New Capabilities

- `release-publishing`: Changelog maintenance, version/tag creation, and a credential-free,
  approval-gated CI workflow that publishes verified release artifacts to PyPI and creates the
  corresponding GitHub Release.

### Modified Capabilities

- None. `continuous-integration` governs pull-request validation and is unaffected; this change
  adds a separate, tag-triggered workflow. `release-verification` (introduced by the in-flight
  `add-release-verification` change) is depended upon, not modified.

## Impact

- New `CHANGELOG.md` at the repository root.
- New `.github/workflows/publish.yml`, triggered on `v*.*.*` tag pushes.
- New "Releasing" section in `CONTRIBUTING.md`.
- Depends on `add-release-verification` being implemented and archived first: the publish
  workflow's build-and-verify job reuses that command instead of re-implementing artifact
  verification.
- Requires a one-time manual step outside CI: registering a PyPI pending trusted publisher for
  `client-query-cache` pointing at this repository, the `publish.yml` workflow, and the `pypi`
  environment.
