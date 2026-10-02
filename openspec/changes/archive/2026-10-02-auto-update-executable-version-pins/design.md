# Design

## Context

See [proposal.md](proposal.md) for motivation. Dependabot already owns supported manifests, Docker FROM/Compose images, action references, and hook revisions. It does not update Python MongoDB literals or arbitrary tool selections. The performance guard requires matching Python interpreters across compared revisions; historical benchmark reports remain evidence rather than update targets.

## Goals / Non-Goals

**Goals:** Use official Renovate integration and built-in managers wherever supported, with explicit ownership, release tracks, and consumer validation.

**Non-Goals:** Replace Dependabot, automate merging, restore Fedora RPM pins, change library behavior or compatibility floors, or rewrite historical reports.

## Decisions

### 1. Use the official hosted app

| Approach                                                                                   | Pros                                                                                 | Cons                                                                        |
| ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ | --------------------------------------------------------------------------- |
| [Official GitHub Action](https://github.com/renovatebot/github-action)                     | Repository-owned workflow; explicit version, schedule, manual runs, and Actions logs | Maintain credentials, workflow, and Renovate upgrades; consumes runner time |
| [Official hosted app](https://docs.renovatebot.com/getting-started/installing-onboarding/) | Least repository infrastructure; service operates Renovate                           | Administrator app installation; less control over runtime and execution     |
| Custom validation harness using Renovate internals                                         | Deterministic assertions for exact inventory and replacement fixtures                | Private API coupling and duplicated runner maintenance; rejected            |

Choose the hosted app to minimize maintained infrastructure. The action is sufficient if repository-controlled execution becomes necessary; it uses the same manager configuration. Do not enable both runners. Validate configuration with Renovate's official pre-commit hook in the existing Prek job; Dependabot owns its revision. Use documented CLI dry runs for extraction and lookup instead of private API imports.

### 2. Keep update ownership disjoint

Enable `github-actions`, `pyenv`, and `custom.regex`. The [Actions manager](https://docs.renovatebot.com/modules/manager/github-actions/) owns only `uses-with` dependencies: uv and just literals in the composite toolchain action and Node's workflow input. Disable its other dependency types so it cannot compete with Dependabot for action references, workflow references, or images.

Use the built-in [pyenv manager](https://docs.renovatebot.com/modules/manager/pyenv/) for `.python-version`; its Docker datasource selects Python release tags, constrained to exact 3.14 patches. Extend Renovate’s official `customManagers:dockerfileVersions` and `customManagers:githubActionsVersions` presets for Prek CI/container selections and Zizmor. Repository-defined regex managers handle only unsupported MongoDB Python literals and the coupled Taplo download. Use a distinct `renovate-taplo` marker so the Dockerfile preset cannot independently update Taplo’s version without its URL and digest. Keep explicit file allowlists and groups for MongoDB and Prek. The pre-commit uv hook and Fedora uv package remain independently owned selections.

### 3. Preserve tracks without blocking timestamp-less sources

Schedule monthly proposals with no automerge or lockfile maintenance. Set seven-day `minimumReleaseAge` with `minimumReleaseAgeBehaviour: timestamp-optional`: releases with timestamps must age, while missing timestamps do not block updates indefinitely. Constrain MongoDB to 8.0 noble, Python to exact 3.14 patches, and Node to 24. Existing manifests retain their Dependabot policies.

DNF installs `bash`, `just`, `nodejs24`, `nodejs24-npm`, and `uv` by package name from Fedora 44. This is the requested unpinned exception: the selected bots cannot safely preserve RPM epochs and architecture selection. Fedora repository updates are expected to have low development-tool breakage risk and are not published library runtime dependencies. Rebuilds can vary; the container contract promises the documented toolchain, not identical RPM revisions. Retain the base-image digest, non-DNF pins, and build/tool smoke checks. Versionlock or transaction replay would introduce a different package-selection policy without providing automatic updates.

### 4. Let consumers read canonical selections

Store CI uv once as a literal `setup-uv` input in the composite action. uv reads `.python-version` during `uv sync`; do not supply a redundant Python override. CI cache keys hash `.python-version`, and setup-uv's cache dependency glob includes it. The container copies that file for Python installation rather than maintaining a duplicate ARG. Published compatibility floors remain unchanged.

Prek installation and cache identity derive from one named CI selection, grouped with the container's PyPI pin. Taplo's regex match spans the ARG, URL, and SHA256. Its stock release-attachment datasource and replacement template update these fields together. The build checks both artifact integrity and `taplo --version`; unresolved or mismatched digests cannot be accepted.

The performance guard installs the proposed revision's interpreter in both base and head environments, records the actual versions, and retains mismatch rejection and visible failure when the base cannot run.

### 5. Validate actual consumer inputs

Containerfile, `.python-version`, and the build checker select the container job. MongoDB selections, the isolated topology/startup test, shared toolchain, interpreter, and Python dependency manifests select benchmark startup. Publishing/release workflows, benchmark report code, and unrelated PR workflow edits do not select either new consumer job. Python package and database-backed checks still cover Python source and shared toolchain changes. Keep expensive consumer jobs behind applicable quality checks.

Maintain the ownership table and stable official CLI commands in contributor documentation. Compare enabled extraction entries with that inventory and review actual update diffs for coupled fields and exclusions. Extraction also lists disabled Actions dependency types; they remain outside Renovate update ownership. Local dry runs are experimental, require configured authentication for GitHub lookups, and perform no branch creation or automatic inventory comparison. Treat skipped dependencies and warnings as incomplete lookup evidence, even when the CLI succeeds. Keep raw output untracked and validation history in commit messages.

## Risks / Trade-offs

- Two updaters can overlap → disable non-`uses-with` Actions dependencies and other manifest managers; review enabled extraction entries against ownership.
- Fedora packages vary across rebuilds → retain Fedora/Node tracks and verify the resulting container tools.
- Missing timestamps permit immediate proposals → preserve maintainer review; apply the age delay wherever timestamps exist.
- Registry or checksum lookup can fail → retain diagnostics and reject unusable proposed downloads through build checks.
- Newly introduced consumer inputs can bypass path selection → update the scope tests when adding inputs.

## Migration Plan

1. Configure built-in managers and the narrowly scoped regex selections without upgrading initial versions. Centralize uv, remove Python override plumbing, and retain the requested DNF exception.
2. Validate the official hook, extraction ownership, affected consumer checks, and matched-interpreter guard behavior.
3. Install the hosted app through repository administration after review. Roll back by disabling it and reverting its configuration; Dependabot retains its ownership.
