# Tasks

## 1. Documentation and Update Tooling

- [ ] 1.1 Classify every optional setting in design inventory group A using Decisions 1–3; remove confirmed redundancies, land each retained behavioral override's explanation in its chosen home, and verify the working ledger contains the classification and applicable evidence/disposition for every occurrence in this group. Include the confirmed Zensical candidates from Context.
- [ ] 1.2 Compare resolved Renovate extraction and policy before/after with the official dry-run commands in `docs/development/executable-version-updates.md`; confirm the MongoDB override, executable inventory, bot ownership, and schedule behavior remain consistent with `openspec/specs/dependency-update-automation/spec.md`, recording version/context evidence alongside the retained explanations.
- [ ] 1.3 Apply Decision 4 in `tests/test_build_versioned_docs.py`: omit `invalid_links` and `invalid_link_anchors` from the disposable `release_repo` configuration, extend the existing failure fixture with a missing local page target separately from the missing-heading and layout cases, and exercise real strict assembly with parametrized cases. Require each broken-target case to fail for its own validation diagnostic, preserve the prior-artifact assertions, and retain successful builds through the same fixture/path. Verify dependency-update test selection against the execution path documented in Decision 4 and the corresponding cases in `tests/test_ci_scope.py`.

## 2. Quality and Test Configuration

- [ ] 2.1 Apply Decisions 1–4 to design inventory group B, including mypy strict-mode expansion, Prek/hook inherited arguments, pytest/plugin defaults, and tool configuration embedded in `pyproject.toml`; verify every optional setting is classified as an evidenced removal, an explained behavioral override, or an ordinary retained project input, with existing validator and quality coverage preserved. Where a removal relies on unstable upstream behavior for a required contract, reuse or add its real-tool behavioral coverage in the same edits.

## 3. Commands and Bootstrap Configuration

- [ ] 3.1 Apply Decisions 1–4 to the justfile, shell/Python scripts, container definitions, and disposable-runtime builders in inventory group C; update affected command documentation in the same edits. Verify each supported wrapper and standalone invocation retains its effective settings; cover required contracts relying on unstable upstream behavior, and add other focused regressions only for command construction or precedence that cannot be established from authoritative resolution alone.
- [ ] 3.2 Apply Decisions 1–3 to the GitHub workflows and composite action in group C; check defaults for removal candidates and behavioral overrides at their pinned action revisions and the platform's documented shell/input behavior. Verify explanations cover retained behavioral overrides affecting permissions, credentials, timeouts, and action/command behavior; inspect the resolved execution paths for unchanged failure propagation and trust boundaries without running privileged workflows.

## 4. Policy Discoverability and Audit Closure

- [ ] 4.1 Complete the tracked-file scan for inventory group D using `git ls-files` and option/flag searches, honoring Decision 1 exclusions; apply the same classification and applicable removal/explanation disposition to every additional owned occurrence, include Decision 4 coverage where applicable, and verify no unclassified candidate remains in the working ledger.
- [ ] 4.2 Add the `CONTRIBUTING.md` and `AGENTS.md` references specified in Decision 3; verify relative links resolve to actual explanation locations and the canonical development-environment requirement after spec synchronization. Verify no link targets a conditional reference document that was not created.
- [ ] 4.3 Reconcile the working ledger with the final diff and explanation destinations: verify every retained behavioral override has one traceable explanation using the delta's omitted-behavior rule, ordinary project inputs have no policy-mandated rationale entries, grouped entries enumerate their occurrences, deleted overrides leave no stale rationale, and every removal/override comparison has authoritative version/context evidence. Verify removal evidence is preserved in each implementation commit body as required by the delta before delivery; keep the working ledger untracked.

## 5. Code Quality

- [ ] 5.1 Scan the entire file for each edited or added test, including pre-existing tests within that file, and apply the `AGENTS.md` Writing Tests guidelines, including parametrization; verify the review covers all such files, or mark inapplicable with a reason if no tests changed.
- [x] 5.2 If you are Claude Code, confirm that you added no new prose to code; all why explanations must go in specs and commit bodies. OpenAI Codex is exempt; this proposal targets Codex's permitted inline comments.
