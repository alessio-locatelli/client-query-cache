## 1. Stabilize and parallelize CI

- [ ] 1.1 Replace workflow-level path exclusions with
      `dorny/paths-filter@de90cc6fb38fc0963ad72b210f1f284cd68cea36` (`v3.0.2`) in a read-only
      change-classification job with a five-minute timeout; verify its catch-all runtime filter
      excludes only Markdown and OpenSpec paths and pull requests with 3,000 or more changed files
      fail open to runtime-affecting coverage.
- [ ] 1.2 Make Docker-backed coverage depend only on change classification and use an `always()`
      condition with `!cancelled()` that runs it for a runtime-affecting change or unsuccessful
      classification; verify it has no quality/build data dependency, an unknown diff cannot skip
      coverage, and a stale run cannot launch coverage after cancellation.
- [ ] 1.3 Upload the warning-level pytest log only when the Docker-backed job fails; verify its
      seven-day retention and safe path remain unchanged.

## 2. Validate the workflow

- [ ] 2.1 Run `just ci-lint` and the repository actionlint hook; verify the edited workflow passes
      both GitHub Actions static checks.
