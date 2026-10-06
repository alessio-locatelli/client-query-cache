# Tasks

## 1. Documentation publication concurrency

- [x] 1.1 In `.github/workflows/docs.yml`, replace the workflow-level `concurrency` block with:

  ```yaml
  concurrency:
    group: ${{ github.ref == 'refs/heads/main' && (github.event_name != 'workflow_run' || github.event.workflow_run.conclusion == 'success') && 'documentation-publication' || format('documentation-skipped-{0}', github.run_id) }}
    cancel-in-progress: true
  ```

  Keep the eligibility condition character-for-character identical to the `build` job's `if`. Verify with `prek run actionlint --files .github/workflows/docs.yml` and `just ci-lint`; the latter runs zizmor with `--fix=all`, so inspect `git diff .github` afterwards and keep only fixes that belong to this change.

- [x] 1.2 Delete the `if:` line from the `deploy` job in `.github/workflows/docs.yml`. Leave `needs: build` in place. Verify that `rg -c "workflow_run.conclusion == 'success'" .github/workflows/docs.yml` prints `2` (the concurrency group and the `build` job).

- [x] 1.3 In `CONTRIBUTING.md`, in the **Publish documentation** paragraph, replace "publication uses a shared queue without cancelling running deployments" with current-behavior prose: a newer eligible run cancels the queued or running publication run, and the site keeps its previous content until the newer deployment succeeds; ineligible runs do not affect eligible ones. After the redeploy sentence, add a short recovery hint: if a run stays queued and does not cancel, an administrator can run `gh api --method POST repos/alessio-locatelli/client-query-cache/actions/runs/<run-id>/force-cancel`, linking GitHub's [force-cancel documentation](https://docs.github.com/en/rest/actions/workflow-runs#force-cancel-a-workflow-run). Keep the paragraph on one line. Verify with `just lint` and `npm run format:check`.

## 2. Code Quality

- [x] 2.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure that the "Writing Tests" guidelines from `AGENTS.md` are applied, including test parametrization. Touches no tests.
- [x] 2.2 If you are Claude Code, confirm that you added no new prose to the code (all "why" explanations must go in the specs and commit bodies). OpenAI Codex is exempt from this rule because it understands the difference between garbage and valuable code comments. Added no code comments.
