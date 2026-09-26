# Tasks

## 1. Rename the installable package

- [ ] 1.1 Check that the `client-query-cache` distribution name can be claimed on PyPI and the GitHub repository name is available; record any name conflict as a blocker before creating a reversible checkpoint for the broad rename.
- [ ] 1.2 Rename `src/mongo_client_cache/` to `src/client_query_cache/` and update project-owned imports in source, tests, and benchmarks; verify no current code imports the old package and focused sync/async import tests pass.
- [ ] 1.3 Rename the distribution in `pyproject.toml`, regenerate `uv.lock`, and update installed-package and CI import checks; verify locked synchronization and clean sdist/wheel installations expose the documented sync and asyncio imports without a source-tree fallback.
- [ ] 1.4 Update sync and asyncio user-visible startup errors that identify the library; verify focused error-path tests report the new identity.

## 2. Update current project identity

- [ ] 2.1 Update README, migration guidance, and current project links with the new name, positioning, installation target, and breaking import substitutions; verify examples import successfully and current links resolve.
- [ ] 2.2 Update contributor container names, labels, workspace paths, and other project-owned automation references; verify the documented setup commands and name-sensitive recipes still target the same environment.
- [ ] 2.3 Update benchmark version lookup to the new distribution; version new decision-evidence output if its old package-name field changes, retain v1 evidence and schema identifiers, and verify new output provenance and existing report validation with focused benchmark tests.

## 3. Complete repository rename

- [ ] 3.1 Check external integrations, rename the GitHub repository to `client-query-cache` after the content is ready, update the local remote, and verify the canonical URL and old-address redirect.

## 4. Code Quality

- [ ] 4.1 Scan every edited or added test file in full for the `AGENTS.md` Writing Tests guidelines, including parametrization; verify any corrections with focused tests.
- [x] 4.2 Inapplicable: the Claude Code prose check does not apply to OpenAI Codex.
