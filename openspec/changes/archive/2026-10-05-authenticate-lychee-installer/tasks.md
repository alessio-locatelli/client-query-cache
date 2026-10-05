# Tasks

## 1. Authenticate Lychee installation

- [x] 1.1 Split `.github/workflows/test.yml` into a token-free general hook invocation and `prek run lychee --all-files` with step-local `GH_TOKEN: ${{ github.token }}`; retain `contents: read`, job identity, pins, cache keys, and dependent gates. Verify with Actionlint and an authenticated hook run using a disposable empty `PREK_HOME`.
- [x] 1.2 Update `docs/development/ci-validation-caches.md` to describe separate Lychee execution, read-only installer authentication, and binary-cache versus result-cache behavior; link the upstream authentication options and verify prose against the workflow and pinned launcher.

## 2. Code Quality

- [x] 2.1 Scan edited test files against the Writing Tests guidelines, including parametrization. No test files are changed; existing workflow validators cover syntax, and the disposable hook run exercises installation.
- [x] 2.2 Confirm Claude Code's prose restriction where applicable. Inapplicable: implemented by OpenAI Codex.
