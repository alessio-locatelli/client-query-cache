# Proposal

## Why

Bot identity and successful validation do not establish that a PR only touches dependency-update files. Unrelated source edits should retain human review.

## What Changes

Implement the file-scope requirement in `specs/dependency-update-automation/spec.md`.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `dependency-update-automation`: acceptance scope.

## Impact

The acceptance workflow, its existing shell-step regression harness, and the canonical executable-update guide. No library API or live repository settings change.
