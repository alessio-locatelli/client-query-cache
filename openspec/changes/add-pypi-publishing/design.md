# Design

## Context

`add-release-verification` (in-flight, tasks not yet started) will add a non-publishing command
that builds sdist and wheel, installs each into an isolated environment, imports the documented
sync and asyncio public surfaces, and checks version/tag consistency. This change's publish
workflow depends on that command existing rather than reimplementing it. No tag, GitHub Release, or
PyPI publish has ever happened for this project, and no `CHANGELOG.md` exists yet, though
`AGENTS.md` already assumes an "Unreleased" changelog section. Commits already carry
conventional-commit titles (`gitlint`'s `contrib-title-conventional-commits`), but only as a style
convention, not as changelog-generation input. Existing GitHub Actions workflows pin every action to
a full commit SHA with a version comment, share a composite `setup-toolchain` action, and scope
`permissions` narrowly (see `.github/workflows/test.yml`,
`.github/actions/setup-toolchain/action.yml`). No GitHub Environment exists on the repository yet.
See proposal.md - Why for the underlying motivation.

## Goals / Non-Goals

**Goals:** A manual, low-tooling release path with no new required dependency; no long-lived PyPI
credential stored anywhere; a human approval gate between "artifacts verified" and "artifacts
published," since a published PyPI version can never be overwritten; one authored source of truth
for release notes.

**Non-Goals:** Automated version bumping or changelog generation from commit history (e.g.
release-please, python-semantic-release, git-cliff) - rejected during exploration in favor of manual
maintainer control, matching a solo-maintainer cadence. Publishing to any registry other than PyPI.
Handling yanking or re-publishing a version - PyPI's own tooling covers that outside this workflow.
Changing how `release-verification` itself builds or checks artifacts - this change only depends on
that command.

## Decisions

- **Reuse `add-release-verification`'s command as the publish workflow's build-and-verify job**,
  rather than reimplementing build/isolated-install/import checks in `publish.yml`. Alternative
  considered: an independent minimal check; rejected because it would duplicate logic that already
  has to exist elsewhere and could silently drift from it.
- **Trigger `publish.yml` on `push: tags: 'v*.*.*'`**, not on `release: published`. A pushed tag is
  the atomic record a maintainer creates locally as part of the documented release steps; gating on
  a hand-authored GitHub Release event would add a second manual step before CI even starts, without
  improving safety, since the environment approval gate (below) already covers that.
- **Authenticate to PyPI via Trusted Publishing (OIDC)** — `permissions: id-token: write` plus
  `pypa/gh-action-pypi-publish` — instead of a stored `PYPI_API_TOKEN` secret. This removes a
  long-lived credential entirely and matches the repository's existing no-stored-secret,
  SHA-pinned-action posture. Alternative considered: an API token secret; rejected as an avoidable
  long-lived credential when trusted publishing is available for GitHub Actions.
- **Gate the upload step behind a protected `pypi` GitHub Environment with a required reviewer**,
  separate from the unattended build-and-verify job. A mistaken or premature tag push stays
  recoverable up to that approval point; PyPI does not allow overwriting or re-uploading a version,
  so this is the last point a mistake can be caught. Alternative considered: fully automatic publish
  on tag push; rejected because the tag push would become the sole, irreversible point of no return.
- **Source GitHub Release notes from the tagged `CHANGELOG.md` section**, parsed at publish time,
  rather than `--generate-notes` or separately hand-written release notes. Keeps `CHANGELOG.md` as
  the single authored source of truth and prevents release notes from drifting from the changelog
  entry a reviewer already approved.
- **Keep changelog maintenance and version bumping fully manual.** This project already uses
  conventional-commit titles for readability, not as changelog-generation input; introducing a
  release-automation tool would add a new dependency and configuration surface for a release cadence
  that doesn't exist yet. This was weighed and explicitly rejected in favor of the manual approach
  during exploration.

## Risks / Trade-offs

- [`add-release-verification` is not yet implemented; building `publish.yml` before it lands would
  either duplicate its logic or block on it] → Sequence tasks so the build-and-verify job is wired up
  only after `add-release-verification` is implemented and archived; treat that as a task
  precondition, not a spec dependency.
- [Manual changelog maintenance can be forgotten in a pull request] → Document it as a standard step
  in `CONTRIBUTING.md`; enforcing it (e.g. via a required check) is out of scope for this change.
- [The one-time PyPI trusted-publisher registration can only be performed by the account owner
  outside this repository, and is easy to get wrong on the first attempt] → Document the exact
  project name, repository owner/name, workflow filename, and environment name to enter, as an
  explicit `CONTRIBUTING.md` prerequisite.
- [A protected environment with no reviewers configured behaves like no gate at all] → Document
  configuring at least one required reviewer on the `pypi` environment as part of the same one-time
  setup.

## Migration Plan

Add `CHANGELOG.md` and the `CONTRIBUTING.md` release-workflow documentation first; neither depends
on `add-release-verification`. Add `publish.yml` only once `add-release-verification` is
implemented and archived, wiring its build-and-verify job to that command. The maintainer completes
the one-time PyPI trusted-publisher registration and configures the `pypi` environment's required
reviewer before pushing the first release tag.
