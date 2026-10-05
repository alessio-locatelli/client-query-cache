# Design

## Context

See [proposal.md](proposal.md) for motivation. Both [PR #160's job](https://github.com/alessio-locatelli/client-query-cache/actions/runs/37283453272/job/111676675382) and [PR #159's job](https://github.com/alessio-locatelli/client-query-cache/actions/runs/37272451479/job/111642152718) log a GitHub API 403 during release discovery, followed by a failed source fallback. The logs do not establish the specific reason for the 403.

The [pinned Lychee launcher](https://github.com/lycheeverse/lychee/blob/lychee-v0.24.2/scripts/lychee_pre_commit.sh) installs through cargo-binstall on a cache miss. [Cargo-binstall's options](https://github.com/cargo-bins/cargo-binstall/blob/main/HELP.md) support `GH_TOKEN` for GitHub authentication and document that `--install-path` cannot select a source-install destination. The existing workflow grants only `contents: read`.

## Goals / Non-Goals

**Goals:** Make release discovery authenticated on fresh runners and limit explicit credential exposure to the hook that needs it.

**Non-Goals:** Replace the upstream launcher, alter link acceptance policy, introduce another tool pin or installation cache, or repair cargo-binstall's source fallback.

## Decisions

Run the other hooks with `SKIP=slotscheck,prettier,lychee`, then invoke `prek run lychee --all-files` with step-local `GH_TOKEN: ${{ github.token }}`. Keep both steps inside the existing Prek job, preserving its required-check identity and downstream gates. `GH_TOKEN` is consumed by cargo-binstall; Lychee's own GitHub link authentication uses `GITHUB_TOKEN`.

Supplying the token to the combined invocation would also expose it to unrelated hooks. A separate installer/action would duplicate the hook's pinned installation and cache ownership. Additional retry logic would not make the unsupported source fallback usable. The chosen split adds one local Prek process and no additional release or link requests compared with the successful existing path.

## Risks / Trade-offs

- Authentication addresses anonymous API access but does not eliminate every GitHub outage or policy rejection; final installation failures remain visible.
- Fork PRs receive GitHub's automatic read-only token; no custom secret is needed. Workflow permissions remain unchanged.
- The hook and checkout can execute PR-controlled code, so the token retains read-only permissions and is scoped to one step.
- A hosted runner's job token cannot be reproduced locally. A disposable cold hook cache can exercise installation with a locally authenticated development CLI session; workflow syntax and permission scope are checked with the existing validators.

## Migration Plan

Apply through the normal PR workflow. Reverting the two hook invocations restores the original installation path. Existing Prek and link-result caches remain compatible.
