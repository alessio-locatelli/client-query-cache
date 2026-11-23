# Proposal

## Why

The root `.gitignore` contains entries copied from a generic Python template. These entries make it harder to see which files this project actually generates or needs to protect from accidental staging.

## What Changes

- Remove unused template entries and their comments, including entries for PyCharm, Spyder, Sphinx, and Pyre. See the design for the removal criteria and the project workflows that need coverage.

## Capabilities

### New Capabilities

### Modified Capabilities

- `development-environment` governs what belongs in the shared Git ignore rules.

## Impact

The implementation changes the root `.gitignore` and affects which untracked paths Git reports to contributors.
