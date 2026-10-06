# Design

## Context

See `proposal.md` for motivation. The existing root `renovate.json5` enables `custom.regex`, `github-actions`, and `pyenv`, limits Actions updates to `uses-with`, groups MongoDB and Prek occurrences, and couples Taplo's version, URL, and checksum. Dependabot owns supported manifests and action references. The configuration disables automerge and lockfile maintenance, ages timestamped releases seven days, and currently permits new branches only before 04:00 UTC on the first day of the month.

Read-only GitHub API checks on 2026-10-06 confirmed the [configuration on main](https://github.com/alessio-locatelli/client-query-cache/blob/main/renovate.json5). Repository automerge is disabled. Effective main-branch rules require one approval and linear history, allow rebase merges, and contain no required-status-check rule. Classic branch protection returns 404 because no classic protection is configured; the effective rules still apply. Mend's authenticated [settings](https://developer.mend.io/github/alessio-locatelli/client-query-cache/-/settings) and [run history](https://developer.mend.io/github/alessio-locatelli/client-query-cache) were inaccessible during planning. Their reported state is unverified, and the reason for no PRs remains unknown.

## Goals / Non-Goals

**Goals:** Make the existing policy maintainable through presets, bound ordinary proposal and CI volume, and give maintainers a reproducible way to identify hosted skip reasons.

**Non-Goals:** Replace Dependabot, broaden executable extraction, change runtime behavior, add a bot runner, or modify hosted or GitHub settings. This proposal does not claim that the reported no-PR symptom is fixed by adding presets.

## Decisions

### 1. Update the recognized configuration in place

Keep `renovate.json5` as the single root configuration. Renovate [recognizes this filename](https://docs.renovatebot.com/configuration-options/#locations-for-configuration-filenames); a second file risks selecting a different policy. Disabling the hosted [required-file guard](https://docs.renovatebot.com/self-hosted-configuration/#requireconfig) avoids configuration discovery but defeats the user's explicit requirement. Neither alternative is needed.

Task 3.2 inspects a recent hosted run read-only, including selected revision, configuration discovery, onboarding state, scheduling, release ageing, lookup errors, and limits. A quiet run may be expected outside the window or when no newer release qualifies. If access is unavailable or logs show an unresolved failure, report that boundary rather than asserting hosted success. Record any persistent discrepancy in contributor docs with a tracking-ticket URL before declaring it resolved. No additional discovery implementation is needed.

### 2. Adopt presets with deliberate ownership overrides

Prepend `config:best-practices` and `:semanticCommits` to the two existing custom-manager presets. Retain manager allowlists, disabled non-`uses-with` Actions types, custom regex managers, coupled groups, allowed versions, age settings, `automerge: false`, and `lockFileMaintenance.enabled: false`.

The [best-practices preset](https://docs.renovatebot.com/presets-config/#configbest-practices) includes recommended policy, Docker/action digest pinning, configuration migration, dependency pinning, and weekly lockfile maintenance. Lockfile maintenance needs an explicit ownership override. Built-in Docker and package-manifest managers remain disabled.

The inherited [Docker digest preset](https://docs.renovatebot.com/presets-docker/#dockerpindigests) matches the Docker datasource across managers. Add `pinDigests: false` to the existing MongoDB package rule, additionally restricting that rule to `matchManagers: ["custom.regex"]` and `matchDatasources: ["docker"]`. Its tag-only replacement does not capture or replace a digest; enabling pinning would change that contract and encounters the limitation tracked in [Renovate issue 24942](https://github.com/renovatebot/renovate/issues/24942). The same official preset already exempts `pyenv`, so do not duplicate that exception. Retain Taplo checksum updates. Expanding MongoDB capture/replacement and consumers to digest references offers stronger pinning but changes extraction and runtime inputs beyond this policy change. Task 2.1 verifies the resolved digest exclusions; no additional research or digest migration is needed.

Hand-copying preset contents is transparent initially but duplicates maintained policy and drifts. Using only `config:recommended` has fewer inherited behaviors but omits the requested best-practice baseline. Prefer best practices with the existing overrides; task 2.1 checks the resolved extraction and ownership. The exact hosted preset version can differ from the pinned local hook, so strict validation and hosted logs remain necessary evidence.

Evaluate the example's remaining options as follows:

| Option                           | Decision and rationale                                                                                                                                                                                                                   |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `pinDigests: true`               | Omit a global duplicate of preset policy; preserve existing checksums and digest pins without expanding managers.                                                                                                                        |
| `group:allDigest`                | Omit for this inventory. Its [digest-only grouping rule](https://docs.renovatebot.com/presets-group/#alldigest) offers little reduction with the existing coupled groups and Taplo download; global grouping can join unrelated updates. |
| `separateMajorMinor: true`       | Omit because it is already the [default](https://docs.renovatebot.com/configuration-options/#separatemajorminor).                                                                                                                        |
| `branchNameStrict: true`         | Omit. GitHub supports Renovate's normal branch names; no observed naming failure requires stripping characters. Stricter names would change bot branch identity without fixing discovery.                                                |
| `platformAutomerge: true`        | Omit. It is already the default and has no role while automerge is disabled.                                                                                                                                                             |
| `rebaseWhen: behind-base-branch` | Keep the default `auto`. For manually reviewed updates, unconditional rebasing on every base advance adds CI work without an existing up-to-date merge requirement.                                                                      |

No further research is needed for the omitted options within this scope.

### 3. Bound proposals and branch commits independently

Set `prConcurrentLimit: 2`, `prHourlyLimit: 1`, and `commitHourlyLimit: 2`. Let `branchConcurrentLimit` inherit the PR limit instead of duplicating it. The [PR budget](https://docs.renovatebot.com/configuration-options/#prhourlylimit) limits new proposals, whereas the [commit budget](https://docs.renovatebot.com/configuration-options/#commithourlylimit) covers branch creation and automatic rebasing. Two commits allow an existing branch refresh alongside new work; one would more readily defer either operation. Three concurrent PRs provide more throughput but add review and CI pressure; two suit this small inventory. No further research is needed for these initial limits.

Use `schedule: ["* * 1-7 * *"]` and explicit `timezone: "UTC"` to fix schedule evaluation independently of hosted defaults. A week each month gives hosted runs and reviewers time to free the two slots. The official `schedule:monthly` preset uses the same narrow four-hour window as the current policy, so a local override is justified. An entire first day still relies on rapid review; unrestricted scheduling would abandon the established monthly cadence. There is no promised backlog-drain time: two unreviewed PRs can still block later updates. No further scheduling research is needed.

Repository [scheduling](https://docs.renovatebot.com/configuration-options/#schedule) restricts branch creation, not Mend polling, and existing branches can still update outside the window under the existing default. Manual rebases bypass the commit budget. Vulnerability alerts bypass ordinary scheduling and hourly limits and normally have separate concurrency behavior. Preserve these official exceptions; do not claim a hard cap on all bot runs or combined Dependabot/Renovate PRs.

Extraction and registry lookups dominate bot-side work; PR validation dominates repository CI cost. These controls bound ordinary new work and automatic commits, not extraction frequency or lookup calls. This change adds no package runtime path, so runtime profiling is inapplicable; hosted activity is not measured during planning.

### 4. Preserve maintainer review

The example's automerge setting is inspiration, while the existing specification expressly prohibits automatic merging. Preserve that contract unless the user selects a different policy. Automated non-major merges reduce review effort but need a separate explicit decision about approval policy and required checks. GitHub supports [platform automerge](https://docs.renovatebot.com/configuration-options/#platformautomerge), but enabling it now would conflict with both the specification and current repository settings. If later approved, require actual CI checks and their lint/format prerequisites, not merely an automerge flag. No automerge research or setting changes are needed to implement the selected review policy.

## Risks / Trade-offs

- Presets evolve and can introduce update behaviors → retain ownership overrides and compare effective dependencies with the existing inventory in task 2.1.
- The monthly window and two review slots can defer a backlog → document the dependency on timely review rather than promise immediate PR creation.
- Mend logs may remain inaccessible → complete repository validation, report hosted verification as unavailable, and do not weaken the guard or invent a cause.
- The hosted app may use newer presets than the local validator → check hosted configuration diagnostics when accessible; keep raw logs untracked and exclude credentials.

## Migration Plan

Update and validate the existing configuration and contributor guide, then deliver the repository change through normal review. After it reaches the default branch, a normal hosted run can discover it; no manual run is an acceptance prerequisite for local implementation. A log showing discovery and either an eligible proposal or an explained skip is hosted evidence; config validation alone is not. Reverting the configuration and guide restores the prior policy without changing Dependabot or hosted settings.
