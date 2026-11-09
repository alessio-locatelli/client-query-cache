# Proposal

## Why

[PR #406](https://github.com/alessio-locatelli/client-query-cache/pull/406) selects Node.js 26, but its development-container build fails because Fedora 44 has no `nodejs26` or `nodejs26-npm` packages. The same DNF failure reproduces in the exact pinned base image.

## What Changes

- Adopt the contributor-image requirements in the `development-environment` delta spec.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `development-environment`: contributor-image repository selection.

## Impact

`Containerfile`, `CONTRIBUTING.md`, and the executable-update inventory. Published library dependencies and CI runner selections are unaffected.
