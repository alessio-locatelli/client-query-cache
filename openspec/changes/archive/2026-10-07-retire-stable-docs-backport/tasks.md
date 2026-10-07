# Tasks

Owner: Codex, implementing this branch through completion.

## 1. Release source cleanup

- [x] 1.1 Delete `stable-docs.toml`, correction-only source helpers and duplicate release diagnostics in `scripts/build_versioned_docs.py`; remove obsolete fixtures/tests in `tests/test_build_versioned_docs.py`. Keep exact-tag/version rejection and independent development selection covered without a correction configuration file.
- [x] 1.2 Remove export-policy inheritance and injected Copy as Markdown features; give disposable release fixtures native exports and cover missing layout/export configuration preserving existing output. Retain real assembled-artifact checks for source-specific export policies and edition isolation.

## 2. Automatic command and CI integration

- [x] 2.1 Implement the shared command described in design decision 1; call it from `.github/workflows/test.yml` and `.github/workflows/docs.yml`. Exercise default discovery against the actual latest release and explicit-tag local reproduction; inspect failure propagation without introducing configuration-text tests.
- [x] 2.2 Remove obsolete path selection from `scripts/ci_scope.py`, its existing parametrization, and publication filters. Add `gh` to `Containerfile` and `scripts/check_dev_container.sh`; verify the image's CLI is executable with the existing container smoke check.
- [x] 2.3 Replace backport/baseline instructions in `CONTRIBUTING.md`, correct the command in `docs/development/ci-validation-caches.md`, and add one current-behavior changelog entry. Verify documented default and explicit-tag invocations against the delivered commands; leave no unassigned cleanup prose.

## 3. Code Quality

- [x] 3.1 Scan both edited test files in full and apply the `AGENTS.md` Writing Tests rules, including parametrization and fixture-owned setup/cleanup.
- [x] 3.2 Claude-specific prose restriction is inapplicable: implementation is by OpenAI Codex.
