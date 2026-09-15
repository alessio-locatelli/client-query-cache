## 1. Verify distributable artifacts

- [ ] 1.1 Add a clean source and wheel build command; verify both artifacts are created from the locked project.
- [ ] 1.2 Install the sdist and wheel into separate isolated environments and import documented sync and asyncio public APIs from each installation; verify missing or unusable files in either artifact fail the check.

## 2. Verify release metadata safely

- [ ] 2.1 Add version and optional tag-consistency checks without publishing credentials; verify mismatches fail with an actionable error.
- [ ] 2.2 Add a non-publishing CI/manual release-verification job and documentation; verify it creates no external package or release state.

## 3. Code Quality

- [ ] 3.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure that the "Writing Tests" guidelines from `AGENTS.md` are applied, including test parametrization.
- [ ] 3.2 If you are Claude Code, confirm that you added no new prose to the code (all "why" explanations must go in the specs and commit bodies). OpenAI Codex is exempt from this rule because it understands the difference between garbage and valuable code comments.
