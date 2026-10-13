# Tasks

## 1. Registration

- [ ] 1.1 Commit version 7 performance and fault registrations before candidate timing; verify their plans preserve version 5 comparisons and version 6 fault applicability.

## 2. Local miss capture

- [ ] 2.1 Implement native capture and validation from the design, with atomic ordering tests and loom models for write/availability/progress fencing.
- [ ] 2.2 Notify the publisher for untracked canonical writes; cover this observer behavior and token rejection through real core mutations.
- [ ] 2.3 Add opt-in owner admission and sync/async adapter routing, including malformed/expired/restarted tokens, native errors, cancellation and legacy fallback; verify that captured misses issue no select RPC and leak no owner handles.

## 3. Evidence

- [ ] 3.1 Collect baseline-only calibration and every registered performance and fault phase from clean commits. Record upper-bound miss comparisons, hot/active gates, every capacity window and bottleneck profiles in the research report; retain failures and incomplete evidence explicitly.

## Code Quality

- [ ] 4.1 Scan entire edited test files for the AGENTS.md Writing Tests guidelines, including parametrization.
- [x] 4.2 Prose restriction is inapplicable: implemented by OpenAI Codex.
