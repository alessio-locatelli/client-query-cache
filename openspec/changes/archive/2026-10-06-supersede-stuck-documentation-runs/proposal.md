# Proposal

## Why

Documentation publication keeps one run per site and never cancels it. When GitHub never assigns a runner to a job, `timeout-minutes` does not apply because it excludes queue time, and the job can remain queued until its run reaches the 35-day limit unless it is cancelled earlier. One such job therefore blocked every later documentation run.

## What Changes

- A newer eligible documentation run requests cancellation of the run holding the site instead of waiting behind it.
- Runs that are ineligible to publish use their own concurrency group, so they cannot cancel or replace an eligible run.
- The deploy job no longer repeats the build job's eligibility condition.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `continuous-integration`: newer documentation publication runs request cancellation of older ones instead of serializing; ineligible runs stay outside the site's concurrency group.

## Impact

Only the documentation workflow and its contributor guidance change. Other workflows keep their concurrency, and every job already sets `timeout-minutes`.
