# Tasks

## 1. Configuration and maintenance

- [x] 1.1 Configure direct public-guide indexing and exclude snippet-wrapper examples; remove the generated-branch publication infrastructure and its tests.
- [x] 1.2 Keep usage rules aligned with current code and canonical guides, and retain same-change maintenance instructions in `AGENTS.md` and `CONTRIBUTING.md`.
- [x] 1.3 Restore the main documentation spec to its base state until final synchronization. Keep ownership-field omission solely in this change's design.
- [x] 1.4 Validate the official schema and repository quality checks, then obtain a clean review. Completion does not depend on post-merge Context7 indexing.

## 2. Code Quality

- [x] 2.1 No test modifications remain; the publication regressions introduced by this change were removed with that infrastructure.
- [x] 2.2 If executing as Claude Code, confirm no new prose was added to code. Inapplicable: OpenAI Codex is exempt.
