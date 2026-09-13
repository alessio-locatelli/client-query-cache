## Why

The hosted CI workflow can be skipped for changes that may still require its status, delays
independent database-backed feedback behind quality checks, and stores a diagnostic log even when
there is no failure to investigate. A focused audit is needed now because the generated workflow
has not received a human review.

## What Changes

- Start CI for every pull request so its required-check status remains stable.
- Use job-level change classification to skip Docker-backed coverage only when a pull request
  changes documentation or OpenSpec artifacts exclusively.
- Run the quality/package and Docker-backed coverage jobs concurrently when the latter is relevant.
- Retain the safe pytest diagnostic only when the Docker-backed job fails.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None.

## Impact

- Updates `.github/workflows/ci.yml` only.
- Keeps existing hosted quality, packaging, coverage, integration, and end-to-end validation.
