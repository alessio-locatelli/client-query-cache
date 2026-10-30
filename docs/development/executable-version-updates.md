# Executable version updates

Dependabot and the official hosted Renovate app propose monthly dependency updates; Dependabot checks the Rust toolchain weekly.
Eligible major updates follow the same policy as minor, patch, and digest updates. After
operator activation, the shared App workflow requests GitHub native auto-merge
using rebase for eligible bot PRs and approves them; required checks gate merging.

| Selection                                                    | Owner                                            | Location                                                                                                                                                                                               |
| ------------------------------------------------------------ | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Manifest dependencies, action references, and hook revisions | Dependabot                                       | Existing supported manifests, `uses:` references, `.pre-commit-config.yaml`                                                                                                                            |
| ast-grep                                                     | Renovate `custom.regex` with PyPI releases       | `additional_dependencies` of the local ast-grep hooks in `.pre-commit-config.yaml`; Dependabot skips local hooks ([dependabot-core#15489](https://github.com/dependabot/dependabot-core/issues/15489)) |
| CI uv and just                                               | Renovate `github-actions`, `uses-with`           | Literal inputs in `.github/actions/setup-toolchain/action.yml`                                                                                                                                         |
| CI and container Node.js                                     | Renovate `nodenv`                                | `.node-version`; CI reads it and the container derives its Node.js/npm major track                                                                                                                     |
| Python                                                       | Renovate `pyenv`                                 | `.python-version`; default development and container selection; CI also retains older supported release lines                                                                                          |
| MongoDB                                                      | Dependabot `docker-compose`                      | `docker-compose.yaml` image tag and digest; the local service, tests, benchmarks, and research harnesses read it                                                                                       |
| Minimum MongoDB                                              | Dependabot `docker-compose`, patch only          | `tests/mongodb-minimum/docker-compose.yaml` image tag and digest; `just test-mongodb-min` reads it                                                                                                     |
| Prek                                                         | Renovate Dockerfile/GitHub Actions presets       | `test.yml` `PREK_VERSION` and Containerfile ARG; one group; cache derives from the CI selection                                                                                                        |
| Zizmor                                                       | Renovate Dockerfile preset                       | Containerfile ARG                                                                                                                                                                                      |
| Taplo                                                        | Renovate regex                                   | Containerfile ARG, download URL, and SHA256                                                                                                                                                            |
| DNF tools                                                    | Fedora repositories                              | Unpinned Fedora 44 RPMs; Node.js track comes from `.node-version`; [rationale](https://github.com/alessio-locatelli/client-query-cache/blob/main/CONTRIBUTING.md#environment)                          |
| Rust toolchain                                               | Dependabot `rust-toolchain`, weekly              | `rust-toolchain.toml`; development, the container default, CI, release builds, and source distributions use it through rustup ([policy](native-quality.md#rust-toolchain))                             |
| Rust crates                                                  | Dependabot `cargo`                               | `native/shared-index/Cargo.toml` and `Cargo.lock`                                                                                                                                                      |
| Native Cargo quality tools                                   | Renovate `custom.regex` with crates.io releases  | Version variables in `justfile`; `just setup-rust` installs them into `.rust-tools/`                                                                                                                   |
| maturin build backend                                        | None; each build resolves the newest 1.x release | `pyproject.toml` build requirement                                                                                                                                                                     |

In this repository, Renovate's Actions manager updates only `uses-with` inputs.
Its other dependency types are disabled to preserve Dependabot ownership. Reports,
test data, local image labels, schema/project versions, and compatibility floors
are excluded.

## Proposal policy

Renovate uses `config:best-practices` and semantic commits. Weekly lockfile
maintenance and experimental configuration migration are excluded; Dependabot
owns lockfiles.
Taplo retains its coupled version, download URL, and checksum replacement; pyenv
inherits the preset's digest exemption. Fedora DNF tools remain unpinned and are
excluded from extraction.

| Bot        | Ordinary update budget                                                                                          | Proposal window                |
| ---------- | --------------------------------------------------------------------------------------------------------------- | ------------------------------ |
| Renovate   | Two concurrent PRs and branches, three new PRs per hour, four automatic branch creation/rebase commits per hour | Days 1–7 of each month, in UTC |
| Dependabot | Two concurrent version-update PRs **per ecosystem**, not across the repository                                  | Monthly; weekly Rust toolchain |

Renovate waits seven days for timestamped releases; missing timestamps do not
block indefinitely. Dependabot retains its seven-day cooldowns. Only the minimum MongoDB pin is capped: it stays on the supported floor's release line until the floor is raised. Renovate maintains the shared
`.node-version`; CI and the development container use the same Node.js major.
Node updates run tooling and container checks. If Fedora cannot provide a proposed
track, the container build fails.

Python updates follow the [support policy](#python-support-policy).

The Rust toolchain is checked weekly instead of monthly because only the newest stable release is [supported](native-quality.md#rust-toolchain): Rust ships a stable release every six weeks, with occasional patch releases in between, and a monthly check could leave the selection a month behind. The seven-day cooldown still applies, so a release is proposed 7 to 13 days after publication. That delay keeps the repository-wide aging rule and gives regressions in a new compiler time to surface, at the cost of adopting fixes about a week later. A toolchain proposal runs the Rust, Python, ARM64, container, and performance-guard checks.

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

Floating requests permit early candidate testing and select stable Python when
the toolchain provides it. The stable `Python compatibility` check fails
if any applicable packaging or test lane fails; see its
[merge enforcement](../../CONTRIBUTING.md#required-checks). Publishing advertised support
also requires the [stable-release acceptance procedure](../../CONTRIBUTING.md#per-release-steps).
The README badge reflects published PyPI classifiers, so it can differ from
development declarations until publication.

## Repository validation

The existing Prek job runs the official configuration validator. To run it locally:

```console
prek run renovate-config-validator --files renovate.json5
```

Fresh Renovate hook installations can emit upstream dependency deprecation
warnings; [#344](https://github.com/alessio-locatelli/client-query-cache/issues/344)
tracks their removal through a supported hook update.

Hosted Python CodeQL extraction environment warnings are tracked in
[#346](https://github.com/alessio-locatelli/client-query-cache/issues/346).
Managed CodeQL cache-restore timeouts are tracked in
[#360](https://github.com/alessio-locatelli/client-query-cache/issues/360).

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

   Require every [stable validation check](../../CONTRIBUTING.md#required-checks)
   with [required status checks](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets#require-status-checks-to-pass-before-merging)
   from the GitHub Actions source, not from a check supplied by the acceptance
   App. Release-specific matrix check names need not be required. Leave “Require
   branches to be up to date before merging” unchecked. Preserve contributor
   approval, stale-review dismissal, linear history, and the permitted rebase
   method; grant the acceptance App no bypass. Loose checks allow a
   non-conflicting PR to merge after main advances, accepting that later base
   changes can interact with previously validated code. Recheck the effective
   main rules afterward.

2. Install or verify the [official hosted Renovate app](https://docs.renovatebot.com/getting-started/installing-onboarding/)
   for this repository. Provision or reuse a **separate acceptance App** with
   Contents and Pull requests write permissions, installed for this repository
   only, with no ruleset bypass. Set repository variable
   `DEPENDENCY_AUTOMERGE_APP_ID` to its App ID and repository secret
   `DEPENDENCY_AUTOMERGE_APP_PRIVATE_KEY` to its private key without logging it.
   [Installation tokens](https://github.com/actions/create-github-app-token)
   are scoped to this repository and those two permissions. The built-in workflow
   token remains read-only. Until both are set, the acceptance run for each
   eligible bot PR fails without requesting a merge or approving; invalid
   credentials or permissions also fail the run.

3. Enable repository auto-merge and verify rebase merging is permitted. The
   workflow only requests auto-merge and never merges directly. GitHub rejects
   the request while repository auto-merge is disabled or when the PR is already
   mergeable, for example after a maintainer approved it; the run then fails
   before approving, and such an approved PR is merged by hand. After
   `Pull request validation` succeeds, the acceptance workflow runs from main
   for both bots. This [completion event can access repository secrets](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run)
   even when validation cannot; [Dependabot-triggered `pull_request_target` cannot](https://docs.github.com/en/code-security/reference/supply-chain-security/dependabot-on-actions).
   No duplicate Dependabot secret is needed.

   Management verifies the validation workflow path, event, head repository, and
   original Dependabot/Renovate actor,
   then uses GitHub's commit-to-PR metadata to select a unique eligible PR. It
   requires a bot author, a same-repository head, main as base, and an open
   non-draft PR whose live head matches the validated commit; several such PRs
   fail the run. It rechecks before requesting credentials, requests native
   auto-merge for that commit, rechecks, and then approves that commit. It
   executes no PR code and consumes no run artifacts or caches. Human pushes to
   bot PRs do not qualify. Normal contributors retain their approval requirement.

   To accept a bot PR opened before activation, re-run its bot-initiated
   validation. The rerun keeps the bot as the run's actor and qualifies at the
   same SHA.

   Verify both Dependabot and Renovate with recorded PR/run links: App approval
   on the latest commit, native rebase acceptance after required CI, and major
   updates using the same path. Check that failed, cancelled, and pending checks
   prevent merging, especially failed Prek with downstream skips. Confirm a
   non-conflicting PR behind main remains eligible; stale completion heads and human,
   fork, draft, or non-main PRs receive no acceptance. Re-run validation for a
   pre-existing PR, then verify a newly created Dependabot PR reaches App
   approval without a rerun or a Dependabot secret. Verify applicable documentation publication after a bot
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
