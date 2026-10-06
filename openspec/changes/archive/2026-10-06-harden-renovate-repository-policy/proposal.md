# Proposal

## Why

Dependency PRs should be created and merged after green CI without routine maintainer action. Improve the existing root Renovate configuration and prepare automatic acceptance for both bots while retaining Mend's required-file guard.

## What Changes

- Reuse official presets with explicit exclusions for unwanted policies and remove release caps; share Renovate-owned Node.js selection between CI and the development container.
- Retain the supported Python compatibility lines in CI while Renovate advances the development interpreter.
- Bound update volume and automate approval and native merging through a metadata-only App workflow.
- Separate the repository PR from post-merge operator activation.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `development-environment`: Share bot-maintained Node.js selection and separate advancing development Python from supported CI compatibility lines.
- `dependency-update-automation`: Automatic acceptance, bounded proposals, preset reuse, and deployment boundaries. The delta spec owns policy values; design owns implementation choices.

## Impact

Change `renovate.json5`, `.github/dependabot.yml`, and `docs/development/executable-version-updates.md`; add `.github/workflows/dependency-automerge.yml`. Add `.node-version` and wire it into CI, the container, its smoke check, and scope selection. Preserve bot ownership, coupled replacements, unpinned RPM exclusions, and existing CI jobs. The code handoff prepares the operator checklist; it does not change live GitHub settings, provision Apps, or write credentials.
