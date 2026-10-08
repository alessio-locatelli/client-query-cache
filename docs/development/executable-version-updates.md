# Executable version updates

Dependabot and the official hosted Renovate app propose monthly dependency updates.
Eligible major updates follow the same policy as minor, patch, and digest updates. After
operator activation, the shared App workflow approves eligible bot PRs and requests
GitHub native auto-merge using rebase; required checks gate merging.

| Selection                                                    | Owner                                      | Location                                                                                                                                                                      |
| ------------------------------------------------------------ | ------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Manifest dependencies, action references, and hook revisions | Dependabot                                 | Existing supported manifests, `uses:` references, `.pre-commit-config.yaml`                                                                                                   |
| CI uv and just                                               | Renovate `github-actions`, `uses-with`     | Literal inputs in `.github/actions/setup-toolchain/action.yml`                                                                                                                |
| CI and container Node.js                                     | Renovate `nodenv`                          | `.node-version`; CI reads it and the container derives its Node.js/npm major track                                                                                            |
| Python                                                       | Renovate `pyenv`                           | `.python-version`; default development and container selection; CI also retains older supported release lines                                                                 |
| MongoDB                                                      | Renovate regex                             | `tests/conftest.py` and `benchmarks/stream_cost/topology.py`; one group                                                                                                       |
| Prek                                                         | Renovate Dockerfile/GitHub Actions presets | `test.yml` `PREK_VERSION` and Containerfile ARG; one group; cache derives from the CI selection                                                                               |
| Zizmor                                                       | Renovate Dockerfile preset                 | Containerfile ARG                                                                                                                                                             |
| Taplo                                                        | Renovate regex                             | Containerfile ARG, download URL, and SHA256                                                                                                                                   |
| DNF tools                                                    | Fedora repositories                        | Unpinned Fedora 44 RPMs; Node.js track comes from `.node-version`; [rationale](https://github.com/alessio-locatelli/client-query-cache/blob/main/CONTRIBUTING.md#environment) |

In this repository, Renovate's Actions manager updates only `uses-with` inputs.
Its other dependency types are disabled to preserve Dependabot ownership. Reports,
test data, local image labels, schema/project versions, and compatibility floors
are excluded.

## Proposal policy

Renovate uses `config:best-practices` and semantic commits. Weekly lockfile
maintenance and experimental configuration migration are excluded; Dependabot
owns lockfiles. The inherited test-directory ignore preset is also excluded so
both MongoDB occurrences remain in one update group. MongoDB retains the `noble`
variant and uses tags without digest pinning because its regex replacement is
tag-only ([upstream limitation](https://github.com/renovatebot/renovate/issues/24942)).
Taplo retains its coupled version, download URL, and checksum replacement; pyenv
inherits the preset's digest exemption. Fedora DNF tools remain unpinned and are
excluded from extraction.

| Bot        | Ordinary update budget                                                                                          | Proposal window                |
| ---------- | --------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| Renovate   | Two concurrent PRs and branches, three new PRs per hour, four automatic branch creation/rebase commits per hour | Days 1–7 of each month, in UTC |
| Dependabot | Two concurrent version-update PRs **per ecosystem**, not across the repository                                  | Existing monthly schedules     |

Renovate waits seven days for timestamped releases; missing timestamps do not
block indefinitely. Dependabot retains its seven-day cooldowns. Neither bot has repository major-version caps. Renovate maintains the shared
`.node-version`; CI and the development container use the same Node.js major.
Node updates run tooling and container checks. If Fedora cannot provide a proposed
track, the container build fails and blocks merging.

Python updates follow the [support policy](#python-support-policy).

The Renovate window permits branch creation when the hosted app runs; it does
not schedule hosted polling. Blocked PRs or unavailable runs can carry a backlog
into the next month. The commit budget limits automatic rebases as well as new
branches; PR creation limits alone do not bound CI runs. Renovate's
[vulnerability alerts](https://docs.renovatebot.com/configuration-options/#vulnerabilityalerts)
bypass these ordinary limits and the window. Manually requested rebases bypass
the [commit budget](https://docs.renovatebot.com/configuration-options/#commithourlylimit).
Dependabot [security updates have a separate PR limit](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-options-reference#open-pull-requests-limit).

## Python support policy

`pyproject.toml` permits installation on Python 3.14 or newer, without an upper
bound. This eligibility does not promise validation of every future interpreter.
The Python version classifiers declare the release lines covered by compatibility
testing. A patch-level development pin does not establish a package requirement;
the earliest eligible patch must pass validation before widening eligibility
([issue #195](https://github.com/alessio-locatelli/client-query-cache/issues/195)).

Renovate advances `.python-version` to stable development releases. The shared
`scripts/ci_python_matrix.py` generator reads the package minimum, classifiers,
and development selection. Packaging and full tests cover the exact earliest
eligible patch (an omitted patch means zero), the exact development interpreter,
and every release line between the minimum and the highest classified or
development line. Lines already represented by either exact request need no
floating request; other lines use major/minor requests. Only identical requests
are deduplicated.

With the current declarations, CI selects `3.14.0`, `3.15`, and `3.14.6`. The
floating request permits early candidate testing and selects stable Python when
the toolchain provides it. The stable `Python compatibility` check blocks merging
if any applicable packaging or test lane fails. Publishing advertised support
also requires the [stable-release acceptance procedure](../../CONTRIBUTING.md#per-release-steps).
The README badge reflects published PyPI classifiers, so it can differ from
development declarations until publication.

## Repository validation

The existing Prek job runs the official configuration validator. To run it locally:

```console
prek run renovate-config-validator --files renovate.json5
```

For inventory inspection, use the [official Renovate CLI](https://docs.renovatebot.com/getting-started/running/)
and its [local dry-run interface](https://docs.renovatebot.com/modules/platform/local/):

For `--platform=local` in both commands: The default is GitHub. We override it because inspection
must read the checkout without updating hosted PRs. For `--dry-run=extract` and `--dry-run=lookup`:
The default is no dry run. We override it because inspection must stop before updates.
For `LOG_LEVEL=debug`: The default is info. We override it because inspection needs resolved
extraction/lookup details ([Renovate 44.133.0 options](https://docs.renovatebot.com/self-hosted-configuration/)).

```console
LOG_LEVEL=debug renovate --platform=local --dry-run=extract
LOG_LEVEL=debug renovate --platform=local --dry-run=lookup
```

Compare enabled dependencies with the ownership table; extraction also lists
Actions dependencies whose updates are disabled. Inspect skipped entries and
warnings, including missing GitHub authentication, even if the CLI exits successfully.
The local platform is experimental and creates no update branches. Review proposed
diffs for coupled versions and Taplo URL/checksum consistency; CI checks their
consumers, including the container build and isolated MongoDB startup.

## Operator activation after merge

A reviewed repository PR prepares the policy and workflow; it does not activate
acceptance. GitHub settings, App provisioning, installation, and credential writes
are operator work after the code lands, not coding-agent tasks. Record activation
evidence and live-state rollback separately from the code PR. Missing administrative
access or credentials blocks activation, not repository delivery.

1. Snapshot the current effective main rules, contributing rulesets or branch
   protection, and repository settings before changing them. Read-only discovery:

   ```console
   gh api repos/alessio-locatelli/client-query-cache/rules/branches/main
   gh api repos/alessio-locatelli/client-query-cache
   ```

   Configure [required status checks](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#require-status-checks-to-pass-before-merging)
   for every stable check in `.github/workflows/test.yml`, including
   `Python compatibility`. That check requires every packaging and test matrix
   lane to succeed; release-specific matrix check names need not be registered
   as required checks. Leave “Require branches to be up
   to date before merging” unchecked. Preserve contributor approval, stale-review
   dismissal, linear history, and the permitted rebase method; grant no bypass.
   Loose checks allow a non-conflicting PR to merge after main advances, accepting
   that later base changes can interact with previously validated code.

   Expected check names from the workflow are listed below. Resolve each exact
   context and its GitHub Actions integration from a successful run before saving
   the rule, and recheck the effective main rules afterward. Scope selection and
   quality prerequisites must independently be required: a failed prerequisite
   can leave downstream jobs skipped. Preserve intentional path-selected skips.

   - `Select validation tiers`
   - `Prek`
   - `Prettier, Markdownlint, and OpenSpec`
   - `Documentation build`
   - `Python compatibility`
   - `Cache memory regression guard`
   - `Cache hot-path performance guard`
   - `Development container build and tools`
   - `Isolated benchmark replica-set startup`

   Use `gh run list --workflow test.yml --status success`, then
   `gh api repos/alessio-locatelli/client-query-cache/actions/runs/<run-id>/jobs`.
   Each job's `check_run_url` identifies its check metadata, including `.name`
   and `.app.id`; require the GitHub Actions source, not a check supplied by the
   acceptance App.

2. Install or verify the [official hosted Renovate app](https://docs.renovatebot.com/getting-started/installing-onboarding/)
   for this repository. Provision or reuse a **separate acceptance App** with
   Contents and Pull requests write permissions, installed for this repository
   only, with no ruleset bypass. Set repository variable
   `DEPENDENCY_AUTOMERGE_APP_ID` to its App ID and repository secret
   `DEPENDENCY_AUTOMERGE_APP_PRIVATE_KEY` to its private key without logging it.
   [Installation tokens](https://github.com/actions/create-github-app-token)
   are scoped to this repository and those two permissions. The built-in workflow
   token remains read-only. Absent configuration produces a visible inactive
   notice and no approval or merge request; invalid credentials or permissions
   fail visibly.

3. Enable repository auto-merge and verify rebase merging is permitted. After
   `Pull request validation` succeeds, the acceptance workflow runs from main
   for both bots. This [completion event can access repository secrets](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run)
   even when validation cannot; [Dependabot-triggered `pull_request_target` cannot](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-on-actions).
   No duplicate Dependabot secret or routine manual dispatch is needed.

   Management verifies the validation workflow path, event, head repository, and
   original Dependabot/Renovate actor,
   then uses GitHub's commit-to-PR metadata to select a unique eligible PR. It
   requires a bot author, a same-repository head, main as base, and an open
   non-draft PR whose live head matches the validated commit. It rechecks before
   requesting credentials, approves that commit, and rechecks before requesting
   native auto-merge for the same SHA. It executes no PR code and consumes no run
   artifacts or caches. Human pushes to bot PRs do not qualify. An operator rerun
   of bot-initiated validation can qualify at the same SHA. Normal contributors
   retain their approval requirement.

   For existing bot PRs, a write-authorized operator can dispatch on main:

   For `--ref main`: The default is the repository's default branch. We override it because
   acceptance must use trusted main independently of that setting
   ([gh 2.97.0 workflow dispatch](https://cli.github.com/manual/gh_workflow_run)).

   ```console
   gh workflow run dependency-automerge.yml --ref main -f pr_number=<number>
   ```

   Verify both Dependabot and Renovate with recorded PR/run links: App approval
   on the latest commit, native rebase acceptance after required CI, and major
   updates using the same path. Check that failed, cancelled, and pending checks
   prevent merging, especially failed Prek with downstream skips. Confirm a
   non-conflicting PR behind main remains eligible; stale completion heads and human,
   fork, draft, or non-main PRs receive no acceptance. Exercise the dispatch path
   for a pre-existing PR, then verify a newly created Dependabot PR reaches App
   approval without dispatch or a Dependabot secret. Verify applicable documentation publication after a bot
   merge: the App token preserves events that
   [`GITHUB_TOKEN` can suppress](https://docs.github.com/en/actions/concepts/security/github_token).

4. Verify hosted configuration discovery as described below. Local validation
   proves neither hosted processing nor activated acceptance.

## Hosted discovery

Keep the hosted required-file guard enabled and retain the single root
`renovate.json5`. In the [Mend-hosted app](https://docs.renovatebot.com/mend-hosted/overview/)
dashboard or logs, verify the repository name, processed revision, and discovered
configuration. Confirm that the processed revision includes the root file and
inspect the resolved managers and exclusions. If there is no PR, inspect the
logged reason: monthly window, release age, available versions, lookup failure,
or PR/branch/commit capacity. File presence alone does not identify the cause.
Record inaccessible hosted evidence as unverified. Create and link a tracking
ticket in this guide for any confirmed persistent discrepancy.

## Rollback

Stop acceptance by disabling its workflow, canceling pending auto-merge requests
with `gh pr merge <number> --repo alessio-locatelli/client-query-cache --disable-auto`,
and withdrawing the acceptance App credentials/access. For `--disable-auto`: The default is
requesting a merge. We override it because rollback must cancel an existing native auto-merge
request ([gh 2.97.0](https://cli.github.com/manual/gh_pr_merge)). Disabling repository auto-merge
alone does not cancel requests already enabled on PRs. Restore
operator-owned settings from the snapshot as appropriate, retaining unrelated
rules. Revert the repository change through a normal reviewed PR for code rollback.
