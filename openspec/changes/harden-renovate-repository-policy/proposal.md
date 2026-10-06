# Proposal

## Why

Dependency updates must progress from automatically created PRs to automatic merging after CI succeeds, without routine maintainer intervention. A recognized `renovate.json5` already exists on the default branch; improve its preset-based policy and configure GitHub acceptance for both Renovate and Dependabot while keeping Mend's required-file guard enabled.

## What Changes

- Reuse official Renovate best-practice and semantic-commit presets without repeating defaults. Exclude inherited weekly lockfile maintenance so Dependabot retains lockfile ownership.
- Enable automatic acceptance for every update type allowed by the existing ownership and release-track policies, including major updates where those policies permit them.
- Use GitHub native automerge after required CI checks pass against the current base, with automatic bot approval to satisfy the existing one-approval rule.
- Add metadata-only bot PR management using a repository-scoped GitHub App token where needed to preserve post-merge workflows.
- Bound ordinary Renovate proposals and automatic branch commits; set Dependabot's version-update limit to two PRs per configured ecosystem.
- Retain monthly updates, seven-day release ageing, coupled executable updates, and the Renovate first-seven-days monthly window.
- Document one-time GitHub setup and read-only diagnosis of hosted configuration discovery and no-PR runs.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `dependency-update-automation`: Replace mandatory manual acceptance with automatic PR creation and CI-gated merging; require preset reuse, bounded update volume, safe bot PR management, and observable repository configuration discovery.

## Impact

Implementation will update `renovate.json5`, `.github/dependabot.yml`, and `docs/development/executable-version-updates.md`, and add `.github/workflows/dependency-automerge.yml`. GitHub setup includes enabling automerge, requiring existing CI checks in the main ruleset, and installing a repository-scoped merge-management App. Existing bot ownership, runtime APIs, CI validation jobs, and Mend's required-file setting remain unchanged. This request revises planning only; live settings and credentials are not modified during planning.
