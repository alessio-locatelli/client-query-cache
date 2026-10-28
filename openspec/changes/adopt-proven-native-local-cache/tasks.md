## 1. Acceptance policy

- [x] 1.1 Update the performance paragraph in `AGENTS.md` to implement the delta's acceptance rule, preserving explicit approval for reproducible costs; retain historical registration in the archived experiment and report.

## 2. Ordinary implementation

- [ ] 2.1 Restore the corrected owner and common contracts from the revision in design.md, remove experiment selection, export the core in ordinary builds, and wire both public managers and public core imports to it. Verify ordinary construction uses the native class while shared coordination uses its observer-capable owner.
- [ ] 2.2 Move the corrected ownership/callback/GC tests into `tests/core`, adapt existing manager fault injection to the actual default, and verify the original triggering events still occur. Audit affected public guides and Context7 rules for API and inspection alignment; add the package benefit to `CHANGELOG.md`.

## 3. Integration evidence

- [ ] 3.1 Execute the acquisition registered in design.md against the normal installed wheel; append source/build identities, outcomes, trade-off decisions, and reproduction commands to `reports/native-process-local-cache/results.md` without removing historical unfavorable evidence.

## Code Quality

- [ ] Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure that the "Writing Tests" guidelines from `AGENTS.md` are applied, including test parametrization.
- [x] If you are Claude Code, confirm that you added no new prose to the code (all "why" explanations must go in the specs and commit bodies). OpenAI Codex is exempt from this rule because it understands the difference between garbage and valuable code comments. (Applied by Codex.)
