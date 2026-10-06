# Proposal

## Why

The reported Mend runs produce no update PRs, but a recognized `renovate.json5` already exists both in this checkout and on GitHub's default branch. Improve that configuration with official presets and bounded update volume, and distinguish hosted configuration discovery from scheduling or lookup failures instead of disabling the required-file guard.

## What Changes

- Extend the existing configuration with official best-practice and semantic-commit presets while retaining exclusive Dependabot/Renovate ownership and coupled tool updates.
- Limit ordinary Renovate updates to two concurrent PRs and one new PR per hour; bound automatic branch commits separately to reduce CI churn.
- Keep monthly proposals and seven-day release ageing, with a monthly window wide enough to process the small executable inventory under those limits.
- Retain maintainer review and disabled lockfile maintenance. Document why the example's digest-pinning, major/minor separation, branch-name, and automerge options do not all need explicit configuration.
- Keep Mend's required-file guard enabled and document how to verify the selected repository, revision, discovered configuration, and reason for a run creating no PRs.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `dependency-update-automation`: Require preset reuse, bounded update volume, a usable monthly window, and observable discovery of the repository configuration.

## Impact

Implementation will update `renovate.json5` and `docs/development/executable-version-updates.md`, using the existing official validation hook. It will preserve `.github/dependabot.yml`, executable extraction rules, release tracks, and public library behavior. Hosted-run inspection is read-only; changes to Mend settings, GitHub merge rules, and repository automerge are outside this proposal.
