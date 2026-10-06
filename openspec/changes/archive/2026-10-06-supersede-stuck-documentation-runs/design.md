# Design

## Context

`.github/workflows/docs.yml` uses the workflow-level concurrency group `documentation-publication` with `cancel-in-progress: false`. Under these settings GitHub runs one workflow run at a time and keeps at most one pending run. A newer pending run cancels the older pending one. The run that holds the group is never cancelled.

Both jobs set `timeout-minutes: 10`, but GitHub counts only execution time. For GitHub-hosted runners, the [Actions limits](https://docs.github.com/en/actions/reference/limits) set no cap on queue time. The only cap is the 35-day limit on a whole run. The 24-hour queue limit applies only to self-hosted runners.

The stuck run shows a GitHub-side failure. Its build succeeded at 14:44:26 UTC, and GitHub created the `github-pages` deployment one second later. That deployment never got a status: not `waiting`, not `queued`, not `in_progress`. The deploy job has no steps, and its run attempt is still `queued`. The environment has only a branch policy and no approval rules. The earlier deployments for the same environment went through `waiting → queued → in_progress → success` within seconds. A few hours later, GitHub reported [an incident delaying runner assignment](https://stspg.io/c11dc9nb1zdq) for Actions and Pages (19:11–22:49 UTC), but this run started before that incident.

Every documentation run checks out `main` and resolves GitHub's latest stable release when it runs, regardless of the event that triggered it. A run's output therefore depends on repository state at run time, not on its trigger.

When `actions/deploy-pages` (pinned `v5.0.1`) receives a cancellation signal, it cancels its Pages deployment. GitHub Pages keeps serving the last successful deployment until a new one succeeds.

## Goals / Non-Goals

**Goals:**

- A stuck documentation run cannot block later publication.
- Runs that cannot publish never cancel or replace a run that can.

**Non-Goals:**

- Detecting or cancelling stuck runs when no newer run arrives.
- Changing concurrency for package publication, PR validation, release verification, or the stream-cost benchmark.

## Decisions

### Newer eligible runs cancel the run holding the site

Set `cancel-in-progress: true` on the documentation group.

- Pros: The next relevant push to `main`, successful release, or manual redeploy clears a stuck run without manual work. Only the newest run matters, because each run rebuilds current state. The current setup already drops intermediate pending runs, so it never ran every trigger anyway. Cancelling a deployment leaves the previous site in place.
- Cons: If pushes to `main` keep arriving faster than one build and deploy, publication waits until they stop. A full run takes about 30 seconds, so this is unlikely.
- Unknowns: GitHub may be unable to cancel a run whose job state is already broken. Testing this would require reproducing a platform failure. If cancellation fails, the run has to be cleared with the [force-cancel API](https://docs.github.com/en/rest/actions/workflow-runs#force-cancel-a-workflow-run), which is documented in `CONTRIBUTING.md` (task 1.3). Nothing else is needed.

Alternatives:

- **Keep serialization (status quo).** Pros: a started deployment always finishes. Cons: one stuck job blocks publication for up to 35 days, and an interrupted Pages deployment gains nothing from finishing because Pages keeps the previous site. Rejected.
- **Scheduled watchdog that force-cancels runs whose jobs stay queued past a threshold.** Pros: catches stuck runs even when no newer run arrives, and could cover every workflow. Cons: custom tooling with `actions: write`, a cron schedule that uses runner time, and possibly no help during an outage that also stops scheduled runs. GitHub has no built-in queue timeout to reuse. This is out of proportion for a docs site that a later push or a manual redeploy can refresh. Rejected. No follow-up is needed.
- **Job-level concurrency (cancellable build, serialized deploy).** Pros: builds can overlap. Cons: a stuck deploy job still holds the serialized deploy group, so it does not fix the failure. Rejected.

### Ineligible runs get their own concurrency group

Use a concurrency group expression that evaluates to `documentation-publication` only for eligible runs. Every other run gets `documentation-skipped-<run_id>`. Eligibility is the condition already used by the build job: `main` ref, and for `workflow_run` events, a successful package-publication conclusion.

GitHub evaluates workflow-level concurrency before job conditions. Without this expression, a run triggered by a failed package publication, or a manual run from another branch, would cancel an eligible run that is deploying. The same problem already exists in the current workflow: such a run can replace an eligible pending run and then skip its own jobs.

- Pros: Fixes both problems without changing triggers.
- Cons: The eligibility condition appears twice, in the group expression and in the build job's `if`. Workflow-level `concurrency` cannot read `env` or job outputs, so the two copies cannot share one definition.
- Unknowns: None.

Alternative: **move concurrency to the jobs**, which do not acquire a group when skipped. Cons: the build and deploy jobs would need separate groups, which brings back the split-group problem above. Rejected. No follow-up is needed.

### Remove the deploy job's duplicated condition

`deploy` needs `build`. GitHub skips a job whose dependency was skipped unless the job's condition overrides that. The deploy job's copy of the eligibility condition therefore never changes the outcome, and removing it leaves one less copy to keep in sync.

## Risks / Trade-offs

- [GitHub cannot cancel a run whose job state is broken] → `CONTRIBUTING.md` documents the force-cancel recovery.
- [A stuck run with no newer run] → Running the workflow manually from `main` supersedes it, as documented in `CONTRIBUTING.md`.

## Migration Plan

Merge to `main`. The workflow change matches the `docs.yml` path filter, so the push starts an eligible run. That run cancels the currently stuck run [37327080405](https://github.com/alessio-locatelli/client-query-cache/actions/runs/37327080405) and replaces the pending run [37425026263](https://github.com/alessio-locatelli/client-query-cache/actions/runs/37425026263). If the stuck run does not cancel, use the documented force-cancel command. To roll back, revert the workflow commit.
