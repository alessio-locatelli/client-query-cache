## Why

The repository's `specifications` Git submodule is currently within several broad tool entry points,
so quality and test commands can spend resources on code outside this project's ownership and may
rewrite it. Every formatter, validator, linter, and pytest invocation needs an explicit exclusion
that remains effective from local recipes, hooks, and CI.

## What Changes

- Define the repository-owned source scope for quality tools and pytest, excluding every path below
  the repository's registered `specifications` Git submodule.
- Apply that boundary to broad Prek hooks and standalone project commands, including write-capable
  formatters, static analysis, and pytest-based test and coverage recipes.
- Retain checks for all repository-owned files and document the boundary for contributors.
- Make the CI command surface inherit the same scoped local recipes, without introducing a separate
  CI-only quality configuration.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `development-environment`: Complete local quality tooling must exclude `specifications`
  Git-submodule contents while continuing to check repository-owned files.
- `test-environment`: Every pytest invocation must avoid collecting or executing
  `specifications` Git-submodule contents.

## Impact

- Affected configuration and command surfaces: `justfile`, `.pre-commit-config.yaml`, Python tool
  configuration, Node formatter/linter configuration, and test configuration.
- Affected automation: GitHub Actions continues to call the scoped `just` recipes.
- No public package API, runtime cache behavior, dependency, or submodule revision changes.
