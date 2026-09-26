# Tasks

## 1. Changelog foundation

- [ ] 1.1 Add `CHANGELOG.md` at the repository root with an "Unreleased" heading and a short comment on the expected entry style (final behavior, one line per change); verify `just format` and Markdownlint pass on the new file.
- [ ] 1.2 Add a step to `CONTRIBUTING.md`'s existing contribution guidance directing contributors to add an entry under "Unreleased" as part of any user-facing change; verify the new guidance reads correctly alongside the existing "Writing Commit Messages" section it sits near.

## 2. Document the release workflow

- [ ] 2.1 Document the one-time PyPI trusted-publisher registration and `pypi` GitHub Environment (with a required reviewer) setup in `CONTRIBUTING.md`, naming the exact project, repository owner/name, workflow filename, and environment values to enter; verify the section names every value without a placeholder.
- [ ] 2.2 Document the per-release steps in `CONTRIBUTING.md` (bump the `version` field in `pyproject.toml`, promote "Unreleased" to `[X.Y.Z] - YYYY-MM-DD`, commit, `git tag vX.Y.Z`, push the tag) and that pushing the tag triggers the approval-gated publish workflow; verify the documented version location matches the field actually declared in `pyproject.toml`.

## 3. Publish workflow

- [ ] 3.1 Confirm `add-release-verification` has been implemented and archived (its `release-verification` capability appears in `openspec list --specs`) and identify the command or `just` recipe it exposes for build plus isolated-install/import verification; record that recipe name for the next task.
- [ ] 3.2 Add `.github/workflows/publish.yml` triggered on `push` of tags matching `v*.*.*`, with a `build-and-verify` job that syncs the locked project and runs the recipe identified in 3.1; verify `just ci-lint` passes and the job fails when a deliberately broken artifact fails verification.
- [ ] 3.3 Add a `publish` job gated by `needs: build-and-verify` and `environment: pypi`, granting only `permissions: id-token: write`, using a SHA-pinned `pypa/gh-action-pypi-publish` step with no token input; verify `just ci-lint` passes and no PyPI credential is read from a repository secret anywhere in the workflow.
- [ ] 3.4 Add a step that extracts the tagged version's `CHANGELOG.md` section and creates the GitHub Release for that tag with it as the body; verify by running the extraction against a sample multi-version `CHANGELOG.md` and confirming it returns only the matching version's section.

## 4. Code Quality

- [x] 4.1 Scan the entire file for edited or added tests and apply the "Writing Tests" guidelines from `AGENTS.md` (touches no Python test files: this change adds only `CHANGELOG.md`, `CONTRIBUTING.md` prose, and a GitHub Actions workflow).
- [ ] 4.2 If you are Claude Code, confirm that you added no new prose to the code (all "why" explanations must go in the specs and commit bodies). OpenAI Codex is exempt from this rule because it understands the difference between garbage and valuable code comments.
