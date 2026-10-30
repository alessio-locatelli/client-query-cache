## Context

See proposal.md for the defects. On 2026-10-30 the repository had no `DEPENDENCY_AUTOMERGE_APP_ID` variable, no `DEPENDENCY_AUTOMERGE_APP_PRIVATE_KEY` secret, repository auto-merge disabled, and no open bot PR. The maintainer chose to keep the workflow and make an unconfigured run fail rather than remove the automation.

## Goals / Non-Goals

Goals: an acceptance run either requests merge and approves the validated head or fails visibly, except for ordinary stale or non-bot runs.

Non-goals: provisioning the App, enabling repository auto-merge, or changing which checks the `main` ruleset requires (tracked in [#358](https://github.com/alessio-locatelli/client-query-cache/issues/358)).

## Decisions

### Unconfigured runs fail after eligibility

The configuration check stays after PR selection, so only eligible bot PRs fail.

- Checking configuration first: fails after every validation run, including human PRs, and gives no PR context. Rejected.
- Removing the workflow: rejected by the maintainer.

### Request auto-merge before approving

The `enablePullRequestAutoMerge` GraphQL mutation, pinned to the validated head with the rebase method, runs before the approval. It only registers auto-merge: GitHub rejects it when repository auto-merge is disabled or the PR is already mergeable, and the job fails before approving. An already-mergeable PR has a maintainer approval, so the maintainer merges it.

- `gh pr merge --auto --match-head-commit`: merges immediately when GitHub already reports the PR mergeable ([gh `isImmediatelyMergeable`](https://github.com/cli/cli/blob/trunk/pkg/cmd/pr/merge/merge.go)), so a run could merge without approving, fail its post-merge recheck, and bypass a disabled repository auto-merge setting. Rejected after review of PR #379.
- Reading `allow_auto_merge` before approving: an additional API call whose visibility to a read-only token is unverified, and the setting can change between check and request. Rejected; the request itself is GitHub's authoritative check.
- Keeping approval first: leaves an App approval without a merge request whenever the request fails. Rejected.

If approval fails after the request, auto-merge stays enabled but the review requirement keeps blocking the merge; the documented `--disable-auto` rollback cancels it. No further work is needed.

### Re-run validation instead of dispatch

The `workflow_dispatch` input and its code path are removed. Re-running a bot-initiated validation run keeps its original actor, so the existing completion path accepts the same head with full validation evidence.

- Keeping dispatch and looking up a successful bot-initiated validation run for the head: avoids a validation rerun, but duplicates the completion path's evidence checks in a second privileged path. Rejected; pre-activation PRs are a one-time case, and the rerun cost is one validation run.

### Start only for bot-initiated validation

The selection job's condition requires a Dependabot or Renovate actor, so other completions skip without a runner, and the step-level actor check is removed. No alternative was considered; the step-level check spent a runner to reach the same result.

### Ambiguous selection fails

Zero matching PRs remain an ordinary skip, such as a stale or closed PR. More than one match fails the run, because same-repository bot PRs normally have distinct heads, so a duplicate indicates an unexpected state that the maintainer should see. No alternative was considered.

## Risks / Trade-offs

- [Every eligible bot PR produces a failed acceptance run until activation] → Accepted by the maintainer; the failure names the missing configuration.
- [Accepting a pre-activation PR costs a full validation rerun] → One-time per PR.
