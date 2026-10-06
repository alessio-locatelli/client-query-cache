# Design

## Context and scope

Renovate owns unsupported executable pins through custom regex, Actions tool inputs, and pyenv; Dependabot owns supported manifests and action references. Keep that split and the existing coupled MongoDB, Prek, and Taplo replacements. [The delta spec](specs/dependency-update-automation/spec.md) is the source for numeric budgets, cadence, release ageing, and acceptance obligations.

## Decisions

### Preset composition

Extend `config:best-practices` and `:semanticCommits` before the existing custom-manager presets. The [best-practices baseline](https://docs.renovatebot.com/presets-config/#configbest-practices) supplies maintained grouping, integrity, pinning, abandonment reporting, and security-age policies within existing ownership. This avoids maintaining a copied list of its constituent policies.

Exclude `:maintainLockFilesWeekly` and `:configMigration` through `ignorePresets`. Lockfiles belong to Dependabot; [configuration migration](https://docs.renovatebot.com/configuration-options/#configmigration) is experimental and creates configuration PRs outside dependency-update scope. Remove local `lockFileMaintenance` and `automerge: false` settings. Renovate's disabled automerge default is intentional: the shared App workflow owns acceptance for both bots, with no `:automergeAll` preset or duplicate merge request.

Remove MongoDB's `allowedVersions` field and the Python/Node rules used solely for version caps. Inherit [Docker versioning](https://docs.renovatebot.com/modules/versioning/docker/) for suffix and precision handling. Add only the necessary MongoDB `pinDigests: false` override, scoped to `custom.regex` and Docker: its replacement is tag-only ([upstream limitation](https://github.com/renovatebot/renovate/issues/24942)). Keep Taplo checksum replacement and the preset's pyenv exemption. Implement the spec's budgets using `prConcurrentLimit`, `prHourlyLimit`, and `commitHourlyLimit`; inherit branch concurrency. Express its monthly window with cron and an explicit UTC timezone.

### Required CI without current-base enforcement

Use GitHub [loose required checks](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#require-status-checks-to-pass-before-merging): require existing checks, but leave “Require branches to be up to date before merging” unchecked. Require every job in `.github/workflows/test.yml`, including scope selection and quality prerequisites; resolve displayed check names and the GitHub Actions source from successful runs during operator activation. Keep path-selected skips, contributor approval, stale-review dismissal, linear history, and the permitted rebase merge method; grant no bypass.

Strict checks would offer stronger integration assurance, but [Dependabot rebasing](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference#rebase-strategy) is conflict- or schedule-driven and cannot guarantee prompt updates after a non-conflicting base push. A branch-update controller adds privileged automation; a merge queue adds validation triggers and platform prerequisites. Loose checks satisfy unattended acceptance with fewer builds, accepting that later base changes may interact with a previously green PR. Omit `rebaseWhen` and inherit Renovate's behavior. No additional controller or queue research is required for this choice.

### Shared App acceptance

Add `dependency-automerge.yml` on trusted `pull_request_target` events: opened, synchronize, reopened, and ready_for_review. Also support `workflow_dispatch` with a PR-number input for one-time activation of existing PRs: require ref main and rely on [GitHub's write-access requirement for dispatch](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/manually-run-a-workflow) to authorize the operator. Use live metadata only; never check out PR code, install from it, consume its artifacts, or write caches. Before requesting credentials, verify the live author is a Dependabot/Renovate bot, head repository matches this repository, base is main, and the PR is open and non-draft. For PR events, also require a bot sender and reject stale event heads; dispatch uses the captured live head. Serialize both paths by PR and submit approval for the verified commit. Recheck the live head before requesting native rebase automerge with `gh pr merge --auto --rebase --match-head-commit "$HEAD_SHA"` for either bot. Approval and merge operations follow [GitHub's documented automation](https://docs.github.com/en/code-security/tutorials/secure-your-dependencies/automate-dependabot-with-actions).

Use SHA-pinned `actions/create-github-app-token` with repository variable `DEPENDENCY_AUTOMERGE_APP_ID` and secret `DEPENDENCY_AUTOMERGE_APP_PRIVATE_KEY`. Scope installation tokens to this repository with Contents/Pull requests write and no bypass. Keep built-in workflow permissions read-only. Without App configuration, report inactive acceptance visibly and perform no approval or merge request.

An App adds one-time setup but preserves post-merge workflows: [GITHUB_TOKEN event suppression](https://docs.github.com/en/actions/concepts/security/github_token) can prevent documentation publication after a bot merge. A PAT adds a personal credential; removing contributor approval weakens the existing review policy. One App path also avoids Renovate's [fallback to direct automerge](https://docs.renovatebot.com/configuration-options/#platformautomerge) before platform activation. Token, review, merge-method, and trigger behavior require operator verification after deployment; task 2.1 prepares those checks.

## Deployment boundary

The coding agent prepares and validates repository files only. Task 2.1 writes a post-merge operator checklist in the contributor guide with this order:

1. Discover and snapshot current effective main rules and repository settings; configure loose required checks without altering unrelated rules or granting bypass.
2. Provision/reuse the scoped App, confirm its installation and permissions, then supply its ID and private-key secret without exposing the key.
3. Enable repository auto-merge and verify both bots' approvals, native rebase merging, failing-check enforcement, behind-base acceptance, and applicable post-merge publication. Dispatch trusted management on main for pre-existing bot PRs as a one-time activation step, using `gh workflow run dependency-automerge.yml --ref main -f pr_number=<number>`.
4. Inspect hosted discovery read-only. File presence and local dry runs establish neither hosted success nor a no-PR cause. Record inaccessible evidence as unverified; persistent discrepancies need a tracking-ticket URL.

Record live operations and their rollback separately from the code PR. Disabling repository auto-merge alone is insufficient for already-enabled PRs: cancel their pending automerge requests, withdraw App credentials/access, and restore operator-owned settings from the snapshot as appropriate. Code rollback is a normal revert. Missing administrative access or credentials blocks activation, not completion of the reviewed repository PR.
