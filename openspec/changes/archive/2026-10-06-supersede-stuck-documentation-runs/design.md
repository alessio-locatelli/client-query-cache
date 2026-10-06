# Design

## Context

See proposal.md - Why. GitHub's [Actions limits](https://docs.github.com/en/actions/reference/limits) bound only execution time per job; the 24-hour queue limit applies to self-hosted runners, so no workflow setting bounds how long a GitHub-hosted job can stay queued. Every documentation run checks out `main` and resolves the latest stable release when it runs, so its output depends on repository state rather than on its trigger.

## Goals / Non-Goals

**Goals:**

- A stuck documentation run does not hold later publication behind it.
- Runs that cannot publish never cancel or replace a run that can.

**Non-Goals:**

- Detecting or cancelling stuck runs when no newer run arrives.
- Changing concurrency for other workflows.

## Decisions

### Newer eligible runs cancel the run holding the site

Use `cancel-in-progress: true` on the documentation group.

- Pros: The next push to `main`, successful release, or manual redeploy supersedes a stuck run. Only the newest run matters because each run rebuilds current state, and GitHub already drops intermediate pending runs. `actions/deploy-pages` cancels its Pages deployment on cancellation, and Pages keeps serving the last successful deployment.
- Cons: Continuous pushes to `main` delay publication until they stop.
- Unknowns: GitHub may fail to cancel a run whose job state is broken; reproducing that requires a platform failure. The repository can only request cancellation, so `CONTRIBUTING.md` documents the [force-cancel API](https://docs.github.com/en/rest/actions/workflow-runs#force-cancel-a-workflow-run) as recovery. Nothing else is needed.

Alternatives:

- **Keep serialization.** Pros: a started deployment always finishes. Cons: one stuck job blocks publication for up to 35 days, and finishing an interrupted Pages deployment gains nothing because Pages keeps the previous site. Rejected.
- **Scheduled watchdog that force-cancels long-queued runs.** Pros: works without a newer run and could cover every workflow. Cons: custom tooling with `actions: write`, recurring runner time, and possibly no help during an outage that also delays scheduled runs. Disproportionate for a site that a later push or manual redeploy refreshes. Rejected; no follow-up is needed.
- **Job-level concurrency (cancellable build, serialized deploy).** Pros: builds can overlap. Cons: a stuck deploy job still holds the serialized deploy group, so the failure remains. Rejected.

### Ineligible runs get their own concurrency group

The workflow-level group expression yields the shared site group only for eligible runs (the build job's existing condition) and a per-run group otherwise. GitHub evaluates workflow-level concurrency before job conditions, so without this a failed package publication or a manual run from another branch would cancel an eligible run, or replace an eligible pending run and then skip its own jobs.

- Pros: Fixes both cases without changing triggers.
- Cons: The eligibility condition appears in the group expression and the build job's `if`; workflow-level `concurrency` cannot read `env` or job outputs, so they cannot share one definition.
- Unknowns: None.

Alternative: **job-level concurrency**, which skipped jobs do not acquire. It reintroduces the split-group problem above. Rejected; no follow-up is needed.

### Remove the deploy job's duplicated condition

`deploy` needs `build`, and GitHub skips a job whose dependency was skipped unless its condition overrides that. The duplicated condition never changes the outcome.

## Risks / Trade-offs

- [GitHub cannot cancel a broken run] → `CONTRIBUTING.md` documents force-cancel recovery.
- [A stuck run with no newer run] → A manual run from `main` supersedes it.
