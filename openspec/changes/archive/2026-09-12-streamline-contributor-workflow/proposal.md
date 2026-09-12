## Why

Contributor guidance duplicates test runs, omits the required Podman-socket step from its primary
agent instructions, and has no dedicated contributor guide. The coverage recipe also performs
separate test runs and combines their data even though the current suite can run in one session.

## What Changes

- Add a focused `CONTRIBUTING.md` as the developer entry point and reorganize development guidance
  so `just coverage` is the normal full test-and-coverage command.
- Make Toolbx and Distrobox contributors enable the host Podman socket before running the default
  coverage command; retain focused recipes and direct pytest for narrower work.
- Simplify `just coverage` to run the current suite once, including the installed-wheel end-to-end
  test, while preserving runtime setup and coverage-integrity checks.
- Retain covdefaults as the coverage-policy source, remove the redundant recipe-level threshold,
  remove redundant coverage-data combining and XML output, remove non-directive workflow comments,
  stop uploading the unused XML artifact in CI, and remove the duplicate CI unit-test job.

## Capabilities

### New Capabilities

- None.

### Modified Capabilities

- `development-environment`: Define concise contributor guidance for the default full validation
  workflow and its required container-runtime preparation.
- `test-environment`: Define the single-run coverage workflow and configuration-owned coverage
  threshold.

## Impact

- Affects `CONTRIBUTING.md`, `AGENTS.md`, `docs/development.md`, `justfile`, `.coveragerc`, and
  `.github/workflows/ci.yml`.
- Does not change the public package API, test topology, or coverage standard.
