# Design

## Context

See `proposal.md` for motivation and `specs/dependency-update-automation/spec.md` for the contract. The privileged workflow uses API metadata without checking out PR code; its existing test harness executes the embedded shell with a stubbed `gh`.

## Goals / Non-Goals

Implement the delta using the existing trusted workflow and harness. Semantic validation of edits within permitted files is outside this change.

## Decisions

### D1: Keep one exact allowlist in the workflow

Use a JSON array in workflow configuration, covering the checked-in updater inventory and existing Actions files. Exact paths prevent newly added scripts or workflows from silently becoming eligible. Maintainers extend the list when adding an updater target.

A source-directory denylist needs less inventory maintenance but admits unknown executable files elsewhere. Glob patterns for workflows reduce maintenance but admit new workflows. Content-aware validation could verify individual version edits but requires parsers and manager-specific replacement rules. The authorized path boundary is proportionate; none of these alternatives needs further investigation for this change.

### D2: Verify once and reuse only for the same diff

In the first acceptance step, read PR metadata, enumerate every files page, compare the count, and check both rename paths with jq. Read metadata again before setting eligibility. Export the checked base SHA and retain the existing head binding; each privileged request rechecks both. A base change during management requires another validation completion rather than reusing a stale diff. An already-behind branch remains eligible when its metadata stays stable during management.

This adds one paginated enumeration and one metadata read to an otherwise eligible run. Repeating the full listing before each mutation duplicates work while its head and base are unchanged. No new checkout, package, action, or persistent cache is needed. The library runtime is unaffected. The test fixture reuses parsed configuration and the stub executable across cases, resetting its output and call log for each invocation.

Matched local measurements of the 11 existing harness cases, with the same contributor configuration and module imports, used six alternating main/head pairs: main median 0.190 s (0.190–0.200), head 0.155 s (0.150–0.160). The 41 added cases measured separately had median 1.255 s (1.210–1.370, six runs). These measure local shell-harness execution, not GitHub network latency. To reproduce, copy the test file, `tests/conftest.py`, and workflow from each revision into matching temporary trees; run `PYTHONPATH="$PWD" uv run -- pytest -c "$PWD/pytest.ini" <tree>/tests/test_dependency_acceptance_workflow.py -n 0 -q -k '(selection or missing_app or approval) and not base-moved'` in alternating order. Invert the selection on head for the added cases. Keep raw outputs untracked.

### D3: Fail closed on incomplete evidence

GitHub's [files endpoint](https://docs.github.com/en/rest/pulls/pulls#list-pull-requests-files) caps responses at 3,000 files. Compare flattened length with the PR count instead of treating successful pagination as completeness. API/JSON/count failures stop the job; a known out-of-scope path emits a notice and skips acceptance.

The [GitHub `diff-entry` schema](https://github.com/github/rest-api-description/blob/main/descriptions/api.github.com/api.github.com.json) requires a recognized status but makes the original filename optional across operations. Check the status before applying the path policy, and require a nonempty original filename for a rename, so missing evidence cannot use the ordinary-file fallback.

## Risks / Trade-offs

Allowed executable files can contain arbitrary edits; this is a path boundary, not proof of a version-only diff. API checks and mutations are separate requests; the retained expected head and fresh metadata checks narrow races without claiming an atomic transaction. Rollback is a normal code revert and requires no live settings change.
