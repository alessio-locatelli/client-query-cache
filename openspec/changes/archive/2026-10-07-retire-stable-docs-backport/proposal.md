# Proposal

## Why

PR documentation validation still builds the superseded release correction even though publication uses a newer release with complete documentation. The manually maintained baseline and unused compatibility paths add maintenance without checking the artifact that will be published.

## What Changes

- Use automatic published-release selection for combined documentation builds.
- Retire the documentation correction configuration and bootstrap support.
- Keep strict assembly, edition isolation, source-specific exports, and recoverable artifact replacement.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `public-library-documentation`: release provenance, automatic validation selection, and native edition exports.
- `development-environment`: GitHub CLI availability for release discovery.

## Impact

The documentation assembler, its tests, both documentation workflows, the command surface, CI scope selection, contributor image, and contributor guidance change. Library runtime APIs and dependencies are unaffected.
