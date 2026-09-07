## 1. Add hosted quality and package validation

- [x] 1.1 Add GitHub Actions quality/build jobs that use `uv sync --locked`, validate the lockfile, build distributions, and install the wheel in isolation; verify workflow syntax and local command equivalents.
- [x] 1.2 Add CPython 3.14 coverage to the appropriate jobs, including the Ruff-extra hook interpreter; verify the rendered matrix has that version.

## 2. Add database-backed verification

- [x] 2.1 Add a Docker-backed integration/end-to-end job using the disposable Testcontainers replica set; verify it has no external database credentials or fixed service dependency.
- [x] 2.2 Preserve safe coverage and failure diagnostics as artifacts; verify artifacts exclude queries, documents, credentials, and resume tokens.

## 3. Verify the CI contract

- [x] 3.1 Exercise every workflow's local equivalent, inspect the final workflows, and verify locked resolution, isolated import, quality, coverage, integration, and end-to-end failure paths.
