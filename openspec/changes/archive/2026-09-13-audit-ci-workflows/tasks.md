## 1. Stabilize and parallelize CI

- [x] 1.1 Replace workflow-level path exclusions with a five-minute, two-commit Git
      change-classification job using the existing pinned checkout action and `fetch-depth: 2`;
      verify its catch-all runtime pathspec excludes only Markdown and OpenSpec paths, has no
      pull-request permission elevation, and fails on a Git comparison error.
- [x] 1.2 Make Docker-backed coverage depend only on change classification and use an `always()`
      condition with `!cancelled()` that runs it for a runtime-affecting change or unsuccessful
      classification; verify it has no quality/build data dependency, an unknown diff cannot skip
      coverage, and a stale run cannot launch coverage after cancellation.
- [x] 1.3 Upload the warning-level pytest log only when the Docker-backed job fails; verify its
      seven-day retention and safe path remain unchanged.

## 2. Validate the workflow

- [x] 2.1 Run `just ci-lint` and the repository actionlint hook; verify the edited workflow passes
      both GitHub Actions static checks.
