# Tasks

## 1. Acceptance workflow

- [x] 1.1 In `.github/workflows/dependency-automerge.yml`, delete the `workflow_dispatch` trigger and its `pr_number` input, the `github.ref == 'refs/heads/main'` and `workflow_dispatch` alternatives of the `select` condition, and the `inputs.pr_number` concurrency fallback. Add `github.event.workflow_run.actor.type == 'Bot'` and a Dependabot/Renovate login check to the `select` condition and delete the step's `jq` actor check. Replace `($head == "" or .head.sha == $head)` with `.head.sha == $head` in `PR_POLICY`. Verify with `uvx prek run actionlint --files .github/workflows/dependency-automerge.yml` and `ZIZMOR_OFFLINE=true zizmor -q --persona=auditor .github/workflows/dependency-automerge.yml`.
- [x] 1.2 In the `select` metadata step, emit `eligible`, `pr_number`, and `head_sha` for exactly one match, a notice for none, and `::error::` with exit 1 for several. Verify by running the step script under `bash --noprofile --norc -eo pipefail` with a stub `gh` on `PATH` returning zero, one, and two matching PRs, plus a failing `gh`.
- [x] 1.3 Make the `configuration` step print `::error::` naming `DEPENDENCY_AUTOMERGE_APP_ID` and `DEPENDENCY_AUTOMERGE_APP_PRIVATE_KEY` and exit 1 when either is empty, and gate the later steps on metadata eligibility only. Verify by running the step script with `CONFIGURED=false` (exit 1) and `CONFIGURED=true` (exit 0).
- [x] 1.4 In the final step, run `verify_pr`, `gh pr merge "$PR_NUMBER" --auto --rebase --match-head-commit "$HEAD_SHA"`, `verify_pr`, then the approval call, keeping each option rationale beside its command. Verify with a stub `gh` that fails the merge request: the approval call must not run.
- [x] 1.5 Update `docs/development/executable-version-updates.md`: unconfigured runs fail, auto-merge is requested before approval and a disabled repository setting fails the run, and pre-activation PRs are accepted by re-running their bot-initiated validation; delete the dispatch command and its option rationale. Verify `rg -n 'dispatch' docs/development/executable-version-updates.md` reports no acceptance dispatch.

## 2. Code Quality

- [x] 2.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure that the "Writing Tests" guidelines from `AGENTS.md` are applied, including test parametrization. Inapplicable: the change edits no tests.
- [x] 2.2 If you are Claude Code, confirm that you added no new prose to the code (all "why" explanations must go in the specs and commit bodies); configuration rationale comments follow the development-environment override requirement.
