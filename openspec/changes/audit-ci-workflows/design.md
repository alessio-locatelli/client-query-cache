## Context

The pull-request-only workflow already has read-only permissions, immutable third-party action
pins, bounded jobs, a cancellation group, dependency caches, and a shared setup action. Its
workflow-level path exclusion can suppress the entire CI status, while the coverage job has no
data or artifacts from the quality/package job and is therefore independent. The pytest log is
configured as a safe, warning-level failure diagnostic in GitHub Actions.

## Goals / Non-Goals

**Goals:** Keep the CI check present for every pull request, skip only irrelevant Docker-backed
validation, reduce feedback latency by expressing only real job dependencies, and avoid
transferring empty or non-actionable successful-run logs.

**Non-Goals:** Add a push, schedule, release, matrix, deployment, or new cache; change the local
validation commands; or alter test coverage.

## Decisions

- Remove workflow-level `paths-ignore`. Branch-protection and ruleset configuration could not be
  read through the GitHub API, so the workflow must not rely on skipped-run semantics for a
  potentially required check.
- Add a short, pinned change-classification job using
  `dorny/paths-filter@de90cc6fb38fc0963ad72b210f1f284cd68cea36` (`v3.0.2`) with only
  `pull-requests: read` in addition to the existing read-only `contents` permission and a
  five-minute timeout. Its runtime-affecting filter includes every path (`**`) and excludes only
  `**.md` and `openspec/**`. The classifier uses the pull request's `changed_files` event value to
  bypass the action when the count is 3,000 or more, because GitHub's pull-request file-list API
  can return at most 3,000 files. The bypass sets the runtime output to true, so an incomplete diff
  can never skip coverage. The quality/package job still runs for every pull request because it
  validates documentation and OpenSpec inputs. A local diff script was considered, but it would
  need full history and custom event handling; the maintained action keeps that GitHub-specific
  logic out of workflow shell.
- Make the Docker-backed coverage job depend only on the classification output and condition it on
  either a runtime-affecting change or classifier failure. Its `if` begins with `always()` so a
  failed classifier does not make GitHub skip the dependent job before evaluating the fallback,
  and includes `!cancelled()` so concurrency cancellation does not launch stale coverage work. The
  job then runs concurrently with quality when relevant or when the diff is unknown; the failed
  classifier still makes the workflow fail.
- Restrict pytest-log upload to job failure. The same seven-day retention and warning-level log
  policy remain, preserving useful diagnosis without routine artifact storage.

## Risks / Trade-offs

- [Change classification cannot read the pull-request diff] → The classifier fails the workflow and
  the Docker-backed job runs through its `always()` fallback; an unknown diff is never safe to skip.
- [A quality failure no longer prevents a relevant Docker job from starting] → It uses more runner
  minutes for a failed pull request but produces independent failure evidence sooner and honors
  the workflow's actual data dependencies.
