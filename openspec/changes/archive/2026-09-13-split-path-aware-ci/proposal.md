## Why

The CI workflow starts every validation tier for every pull request and uses a custom change-classification
job only to suppress database-backed testing. Native GitHub Actions path filters can select the relevant
workflow without checking out history or reimplementing Git diffs.

## What Changes

- Split pull-request validation into independently triggered quality, formatting, and database-test workflows.
- Run Prek for every pull request, excluding its Prettier hook when a path-filtered Prettier workflow owns
  that validation.
- Limit the database-backed coverage workflow to Python and test-configuration changes.
- Remove the custom runtime-change classifier and its full-history checkout.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `continuous-integration`: Select hosted validation tiers from their relevant changed files while preserving
  locked dependency, packaging, formatting, and database-test guarantees.

## Impact

- Replaces `.github/workflows/ci.yml` with purpose-specific pull-request workflows.
- Updates the CI requirement and its scenarios; no package runtime interface or dependency changes.
