# Design

## Context

See `proposal.md` for motivation. Renovate's existing config owns `custom.regex`, Actions `uses-with`, and `pyenv` updates; Dependabot owns supported manifests and action references. MongoDB and Prek have coupled groups, and Taplo replacements couple version, URL, and checksum. The current config restricts MongoDB to 8.0, Python to 3.14, and Node to 24; remove those caps while retaining seven-day ageing.

Read-only GitHub checks on 2026-10-06 confirmed [renovate.json5 on main](https://github.com/alessio-locatelli/client-query-cache/blob/main/renovate.json5). Repository automerge is disabled. Active main ruleset 1991678 requires one approval, dismisses stale approvals, permits rebase merges, and has no required-status-check rule. Actions defaults to read-only permissions and cannot approve PRs with its built-in token. There is no existing App-token workflow in this checkout. Mend's [settings](https://developer.mend.io/github/alessio-locatelli/client-query-cache/-/settings) and [run history](https://developer.mend.io/github/alessio-locatelli/client-query-cache) were inaccessible during planning; the reported no-PR cause remains unverified.

## Goals / Non-Goals

**Goals:** Automatically create and accept updates from both bots, including newer major versions under the same CI gates, using native GitHub merge enforcement and official presets with minimal local configuration.

**Non-Goals:** Broaden executable extraction, change runtime behavior, replace Dependabot, add a self-hosted updater, weaken the required-file guard, or execute deployment during planning.

## Decisions

### 1. Reuse presets without restating defaults

Extend `config:best-practices`, `:semanticCommits`, and [:automergeAll](https://docs.renovatebot.com/presets-default/#automergeall), followed by the two existing custom-manager presets. Remove `automerge: false`; do not repeat the preset's `automerge: true`. Keep extraction allowlists, ownership exclusions, groups, and age settings.

Remove MongoDB's `allowedVersions` field and the Python/Node rules whose only purpose is restricting `allowedVersions`. Major releases use the same automatic proposal, approval, and merge path as other releases. Retaining caps would require routine maintainer intervention despite passing CI. Inherit [Docker versioning](https://docs.renovatebot.com/modules/versioning/docker/) for MongoDB's existing image suffix and tag precision; do not replace the cap with a custom noble filter or a major-enable rule that restates enabled behavior. Unpinned DNF package installs remain outside version extraction and resolve from the selected Fedora base; no repository RPM updater is added. Task 1.3 checks major candidate eligibility in the effective policy.

The base [lockFileMaintenance default](https://docs.renovatebot.com/configuration-options/#lockfilemaintenance) is disabled, but [best practices](https://docs.renovatebot.com/presets-config/#configbest-practices) includes `:maintainLockFilesWeekly`, which enables it. Set `ignorePresets: [":maintainLockFilesWeekly"]` using the official [nested preset exclusion](https://docs.renovatebot.com/configuration-options/#ignorepresets), and delete the local `lockFileMaintenance` object. This retains Dependabot ownership by excluding the unwanted policy, without repeating the base default. Simply deleting the object while leaving that subpreset active would enable maintenance. Copying the remaining subpresets would duplicate maintained preset composition; using only recommended policy would lose the broader best-practice baseline. Task 1.1 validates resolution; no further preset research is needed.

The inherited [Docker digest preset](https://docs.renovatebot.com/presets-docker/#dockerpindigests) matches Docker datasources across managers. Add `pinDigests: false` to the existing MongoDB rule, scoped to `custom.regex` and datasource `docker`. This is a necessary inherited-policy override: MongoDB's tag-only replacement cannot capture or replace a digest, as illustrated by [Renovate issue 24942](https://github.com/renovatebot/renovate/issues/24942). The official preset already exempts `pyenv`; do not duplicate that exception. Retain Taplo checksum updates. Expanding MongoDB replacement and consumers for digest references is outside this change; task 1.3 verifies resolved behavior and no migration research is required.

| Option                           | Decision                                                                                                                                  |
| -------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------- |
| `platformAutomerge: true`        | Inherit the supported default; native GitHub automerge is used.                                                                           |
| `automergeType: pr`              | Inherit the default; keep visible PRs and branch-rule enforcement.                                                                        |
| `automergeStrategy: auto`        | Inherit the default; GitHub permits only rebase merging here. Verify that the native request uses that method.                            |
| `separateMajorMinor: true`       | Inherit the default; do not repeat it.                                                                                                    |
| `pinDigests: true`               | Omit globally; use the preset and the necessary MongoDB exception.                                                                        |
| `group:allDigest`                | Omit; existing coupled groups and the Taplo download offer little useful additional digest grouping.                                      |
| `branchNameStrict: true`         | Omit; no observed GitHub naming failure justifies changing bot branch identity.                                                           |
| `rebaseWhen: behind-base-branch` | Set explicitly. Native automerge with `auto` does not guarantee rebasing; strict current-base checks require updates after main advances. |

The omitted options need no additional research within this scope.

### 2. Bound work without depending on manual merges

Set Renovate `prConcurrentLimit: 2`, `prHourlyLimit: 3`, and `commitHourlyLimit: 4`; inherit the branch concurrency budget. Three proposals per hour avoids the unnecessary delay of a one-PR hourly limit while retaining a small concurrent queue. The separate [commit budget](https://docs.renovatebot.com/configuration-options/#commithourlylimit) covers ordinary automatic creation and rebasing, which a PR budget does not; four leaves room for three new branches plus a rebase, subject to available concurrent capacity. Use `schedule: ["* * 1-7 * *"]` and `timezone: "UTC"` for the monthly proposal window. The standard monthly preset's four-hour window is too narrow for a deliberately throttled queue. A full first week leaves time for hosted runs, checks, and rebases; unrestricted creation would abandon the established monthly cadence.

Add `open-pull-requests-limit: 2` to each existing Dependabot ecosystem entry, retaining schedules and cooldowns. This differs from its default of five. Six entries permit up to twelve ordinary version-update PRs, not a global limit of two. Grouping unrelated dependencies merely to simulate a global cap would reduce independent failure diagnosis; adding a custom global scheduler would duplicate bot infrastructure. No further limit research is needed.

Schedules and budgets do not control Mend polling. Renovate manual rebases and vulnerability alerts have documented budget exceptions; Dependabot security updates have separate limits. Existing Renovate branches can still update outside the creation window. CI and registry work remain the main resource costs; no runtime profiling is applicable. These are configured controls, not measured hosted-run reductions.

### 3. Use GitHub native enforcement for green CI

Enable repository `allow_auto_merge`. Add required status checks to the existing main ruleset, sourced from the GitHub Actions App, with strict current-base validation. Retain one approval, stale-review dismissal, linear history, and the existing permitted merge method; give neither updater nor merge-management App a ruleset bypass.

Require the existing stable checks from `.github/workflows/test.yml`:

- Select validation tiers
- Prek
- Prettier, Markdownlint, and OpenSpec
- Documentation build
- Static checks, packaging, and isolated install
- Docker-backed integration, end-to-end, and coverage
- Cache memory regression guard
- Cache hot-path performance guard
- Development container build and tools
- Isolated benchmark replica-set startup

Requiring scope selection and quality prerequisites prevents skipped dependent jobs from hiding failed prerequisites. Existing intentionally inapplicable jobs may skip; applicable checks must finish successfully for the latest tested revision. Preserve the existing path-aware validation and cheap-before-expensive execution. An aggregate custom gate is unnecessary because existing job identities and required-check enforcement provide this behavior.

GitHub [native automerge](https://docs.renovatebot.com/configuration-options/#platformautomerge) waits for required checks and approvals. A workflow that manually polls CI and invokes unconditional merge would duplicate enforcement and introduce race handling. A merge queue could test combined changes but requires different workflow triggers and is disproportionate to these limits; strict current-base validation provides the selected contract. Task 2.2 verifies rules and task 3.2 covers platform behavior; no additional gate architecture research is needed.

### 4. Automate approval without executing bot PR code

Add `.github/workflows/dependency-automerge.yml` with `pull_request_target` for `opened`, `synchronize`, `reopened`, and `ready_for_review`. The workflow uses trusted default-branch code and live PR metadata only, with no checkout, installs from the PR, cache writes, or PR artifacts. Check both event sender and live PR author against `dependabot[bot]` and `renovate[bot]`, require bot account types, same-repository head, open non-draft PR, and base `main`. Branch names and titles never authorize access. Confirm the live head matches the event head immediately before submitting approval; approval targets that commit. Serialize management by PR so old events cannot race new heads.

Use a separate GitHub App installed only on this repository, with Contents and Pull requests write permissions and no ruleset bypass. Store its ID as `DEPENDENCY_AUTOMERGE_APP_ID` and private key as `DEPENDENCY_AUTOMERGE_APP_PRIVATE_KEY`; never read or print the key. Issue short-lived repository-scoped tokens through the official [actions/create-github-app-token](https://github.com/actions/create-github-app-token), pinned according to repository conventions. Retain read-only built-in workflow defaults and the disabled built-in Actions-approval setting: App review permissions satisfy the one-approval rule instead. Reapprove bot revisions after their automatic rebases because stale reviews are dismissed.

The App approves both bots' eligible PRs. For Dependabot, it also runs `gh pr merge --auto --rebase --match-head-commit "$HEAD_SHA"` for the verified PR. Renovate requests native automerge using its own hosted App through `:automergeAll`; do not duplicate that request in the workflow. No update-type filter is added. The merge-management App performs acceptance only and never runs dependency extraction or writes update branches.

GitHub's [documented CLI automation](https://docs.github.com/en/code-security/tutorials/secure-your-dependencies/automate-dependabot-with-actions) supplies the approval/merge operations. The built-in `GITHUB_TOKEN` would avoid an App installation but its [event suppression](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow) can prevent the existing documentation workflow from running after a Dependabot merge changes `uv.lock` or another watched input. A scoped App token preserves those events without adding publication triggers. A PAT introduces a user credential; removing required approval would weaken all contributor PRs. The scoped App is the selected tradeoff. Provisioning and permissions remain an implementation prerequisite in task 2.3; task 3.2 verifies token behavior and missing credentials remain a visible deployment blocker, not successful activation.

### 5. Keep discovery diagnosis separate from activation evidence

Retain the single recognized root `renovate.json5` and hosted required-file guard. Use existing official validation and extraction/lookup dry runs, inspecting resolved inherited behavior as well as extraction. Add concise contributor guidance for repository/revision selection, configuration discovery, onboarding, schedule, release ageing, lookup errors, and budgets. Task 3.3 attempts read-only Mend inspection; inaccessible logs do not establish a cause or hosted success. Any observed persistent discrepancy needs a tracking-ticket URL in docs. A second config or disabling the guard is unnecessary; no new diagnostic runner is needed.

## Risks / Trade-offs

- Major updates can break behavior that CI does not cover → require all applicable validation against the current base; do not impose version caps or extra manual acceptance solely because an update is major.
- App setup adds one-time administration → reuse official token tooling and document exact permissions and credential names; missing setup blocks activation visibly.
- Presets and hosted versions evolve → strict validation and effective-policy inspection verify ownership, digest exceptions, lockfile exclusion, and automerge.
- Base advances trigger additional CI → strict current-base enforcement protects combined updates; throttling limits ordinary Renovate automatic commits.
- Hosted runs remain unobservable without Mend access → report that evidence boundary; do not weaken the guard or claim the no-PR symptom is fixed.

## Migration Plan

Prepare repository changes and concise setup docs first. Configure required checks and the scoped App before enabling automerge behavior, so no bot PR can merge without CI enforcement. Apply the repository configuration and trusted workflow through normal review, then enable repository automerge and verify the activation cases. Preserve a metadata-only workflow on the default branch; do not enable execution of bot PR code in privileged jobs.

Rollback by disabling repository automerge and removing bot management, reverting update-policy changes while retaining required validation and ordinary contributor approval. If App provisioning, administrative access, or GitHub feature support is missing, report the concrete blocker and leave automatic acceptance inactive. A local validator passing does not complete deployment verification.
