# Tasks

## 1. Documentation publication concurrency

- [x] 1.1 In `.github/workflows/docs.yml`, make the workflow-level concurrency group resolve to `documentation-publication` only when the build job's eligibility condition holds and to a group containing `github.run_id` otherwise, and set `cancel-in-progress: true`. Verify with `prek run actionlint --files .github/workflows/docs.yml` and `just ci-lint`.
- [x] 1.2 Remove the `deploy` job's `if:` condition, keeping `needs: build`. Verify the eligibility condition remains only in the concurrency group and the `build` job.
- [x] 1.3 In the **Publish documentation** paragraph of `CONTRIBUTING.md`, describe that a newer eligible run cancels the queued or running one while the site keeps its previous content, that ineligible runs do not affect eligible ones, and how an administrator force-cancels a run that does not cancel. Verify with `just lint` and `npm run format:check`.

## 2. Code Quality

- [x] 2.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure that the "Writing Tests" guidelines from `AGENTS.md` are applied, including test parametrization. Touches no tests.
- [x] 2.2 If you are Claude Code, confirm that you added no new prose to the code (all "why" explanations must go in the specs and commit bodies). OpenAI Codex is exempt from this rule because it understands the difference between garbage and valuable code comments. Added no code comments.
