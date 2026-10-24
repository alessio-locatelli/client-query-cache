# Tasks

## 1. Native production measurement

- [ ] 1.1 Implement the isolated combined-measurement flow in design.md using a pinned cargo-llvm-cov tool; document prerequisites and measured scope. Verify the report includes every production Rust module and Python binding bodies, uses fresh profiles, emits no aggregation warnings, and leaves the ordinary project installation unchanged.
- [ ] 1.2 Reproduce every uncovered path from the established report; add behavior tests, remove proven dead code, or document a technically justified generated/platform exception at its source. Include the boundary and lifecycle cases listed in design.md, retain existing tests, and compare affected runtime metrics with main if production code changes. Verify 100% production line/function coverage without broad exclusions.

## 2. Coverage gate integration

- [ ] 2.1 Integrate the completed coverage command after native static checks in CI and into the documented local workflow, using the existing native tier and executable cache. Verify a deliberately uncovered production path fails the command and CI uses the same threshold without repeating the suite in each Python lane.

## 3. Code Quality

- [ ] 3.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure the Writing Tests guidelines from AGENTS.md are applied, including test parametrization.
- [x] 3.2 Confirm no new prose was added to code if using Claude Code. Inapplicable: planning by OpenAI Codex.
