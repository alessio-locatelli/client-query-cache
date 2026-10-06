# Proposal

## Why

The documentation workflow keeps one run per site and never cancels it. On 2026-10-05, GitHub created the Pages deployment for run [37327080405](https://github.com/alessio-locatelli/client-query-cache/actions/runs/37327080405) but never gave its deploy job a runner. The job stayed `queued`, and `timeout-minutes` does not count queue time. Later documentation runs were cancelled while pending or kept waiting behind it ([37425026263](https://github.com/alessio-locatelli/client-query-cache/actions/runs/37425026263)). GitHub cancels a stuck hosted-runner run only after its 35-day run limit, so one platform failure can block documentation publication for weeks.

## What Changes

- A newer eligible documentation run cancels the run that currently holds the site's slot, whether that run is queued, building, or deploying. Only the newest run matters because each run rebuilds current `main` and the latest stable release.
- Runs that skip their jobs (manual runs from another branch, or completed package-publication runs that did not succeed) use their own concurrency group, so they cannot cancel or replace an eligible run.
- The duplicated eligibility condition on the deploy job is removed. The deploy job already depends on the build job and is skipped when the build job is skipped.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `continuous-integration`: publication runs for the same site now supersede one another instead of waiting behind an in-progress run. Ineligible runs stay outside the site's concurrency group.

## Impact

Only `.github/workflows/docs.yml` changes. Package publication, PR validation, and the other manual workflows keep their current concurrency. Every job already sets `timeout-minutes`, so nothing new is needed there. GitHub has no setting that limits how long a hosted-runner job can stay queued, so this change limits the damage of a stuck run but does not detect one. If cancelling a stuck run also fails, it has to be cleared through GitHub's force-cancel API.
