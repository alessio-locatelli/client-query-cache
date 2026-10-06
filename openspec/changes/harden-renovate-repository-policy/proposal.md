# Proposal

## Why

Dependency PRs should be created and merged after green CI without routine maintainer action. Improve the existing root Renovate configuration and prepare automatic acceptance for both bots while retaining Mend's required-file guard.

## What Changes

- Reuse official presets with explicit exclusions for unwanted policies and remove bot-managed release caps.
- Bound update volume and automate approval and native merging through a metadata-only App workflow.
- Separate the repository PR from post-merge operator activation.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `dependency-update-automation`: Automatic acceptance, bounded proposals, preset reuse, and deployment boundaries. The delta spec owns policy values; design owns implementation choices.

## Impact

Change `renovate.json5`, `.github/dependabot.yml`, and `docs/development/executable-version-updates.md`; add `.github/workflows/dependency-automerge.yml`. Preserve bot ownership, coupled replacements, unpinned DNF exclusions, and existing CI jobs. The code handoff prepares the operator checklist; it does not change live GitHub settings, provision Apps, or write credentials.
