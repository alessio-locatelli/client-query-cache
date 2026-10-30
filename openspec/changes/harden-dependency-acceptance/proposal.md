## Why

The dependency acceptance workflow reports success without doing anything while its App is unconfigured, which is its live state. Its manual dispatch path approves a pull request without evidence that validation passed for the head commit. It also approves before requesting auto-merge, so with repository auto-merge disabled (also the live state) a configured App would leave an approval behind without a merge request.

## What Changes

- An eligible bot pull request whose acceptance App is unconfigured fails the acceptance run instead of passing with a warning.
- Native auto-merge is requested for the validated head before approval, so a rejected request fails the run before any approval exists.
- Several eligible pull requests for one validated head fail the run instead of being skipped.
- Acceptance starts only for validation runs initiated by Dependabot or Renovate; other completions skip the job.
- **BREAKING** (operator procedure): the manual `workflow_dispatch` path is removed. A bot pull request opened before activation is accepted by re-running its bot-initiated validation.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `dependency-update-automation`: Inactive configuration fails visibly, approval follows a successful auto-merge request, ambiguous selection fails, and pre-activation pull requests use validation reruns.

## Impact

`.github/workflows/dependency-automerge.yml` and `docs/development/executable-version-updates.md`. No repository setting, App, or credential changes.
