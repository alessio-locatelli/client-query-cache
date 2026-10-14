# Tasks

## 1. Registration

- [x] 1.1 Commit version 7 performance and fault registrations before candidate timing; verify their plans preserve version 5 comparisons and version 6 fault applicability.
- [x] 1.2 Commit the version 8 queue registration before timing; freeze its rates only from fresh baseline calibration.

## 2. Local miss capture

- [x] 2.1 Implement native capture and validation from the design, with atomic ordering tests and loom models for write/availability/progress fencing.
- [x] 2.2 Notify the publisher for untracked canonical writes; cover this observer behavior and token rejection through real core mutations.
- [x] 2.3 Add opt-in owner admission and sync/async adapter routing, including malformed/expired/restarted tokens, native errors, cancellation and legacy fallback; verify that captured misses issue no select RPC and leak no owner handles.
- [x] 2.4 Preserve data-channel reconnection for local misses in new threads and after transport loss; reject oversized combined frames without disconnecting the owner channel.
- [x] 2.5 Implement the native admission queue from the design, including bounded publication/reuse, socket fallback, peer isolation and startup sampling; validate both adapter models and queue ordering.

## 3. Evidence

- [x] 3.1 Record the complete version 7 study and profiles, retaining its failed miss bounds.
- [x] 3.2 Collect every version 8 phase from clean commits and record its decision under the unchanged protocol.
- [ ] 3.3 After [issue #278](https://github.com/alessio-locatelli/client-query-cache/issues/278) establishes the benchmark protocol, follow the [continuation handoff](https://github.com/alessio-locatelli/client-query-cache/issues/279) to reduce the remaining miss cost and collect fresh registered evidence that passes every required issue #272 bound; version 8 does not meet acceptance.

## Code Quality

- [x] 4.1 Scan entire edited test files for the AGENTS.md Writing Tests guidelines, including parametrization.
- [x] 4.2 Prose restriction is inapplicable: implemented by OpenAI Codex.
