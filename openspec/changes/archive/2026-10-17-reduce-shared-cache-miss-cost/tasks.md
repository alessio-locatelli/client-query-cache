# Tasks

## 1. Registration

- [x] 1.1 Commit version 7 performance and fault registrations before candidate timing; verify their plans preserve version 5 comparisons and version 6 fault applicability.
- [x] 1.2 Commit the version 8 queue registration before timing; freeze its rates only from fresh baseline calibration.

## 2. Local miss capture

- [x] 2.1 Implement native capture and validation from the design, with atomic ordering tests and loom models for write/availability/progress fencing.
- [x] 2.2 Notify the publisher for untracked canonical writes; cover this observer behavior and token rejection through real core mutations.
- [x] 2.3 Add opt-in owner admission and sync/async adapter routing, including malformed/expired/restarted tokens, native errors, cancellation and legacy fallback; verify that captured misses issue no select RPC and leak no owner handles.
- [x] 2.4 Preserve socket-admission reconnection for local misses in new threads and after data-channel loss; reject oversized combined frames without disconnecting the owner channel.
- [x] 2.5 Implement the native admission queue from the design, including bounded publication/reuse, socket fallback, peer isolation and startup sampling; validate both adapter models and queue ordering.
- [x] 2.6 Reduce the measured copying, guard and drain costs from the design without weakening lock ordering or admission fences; cover fragment boundaries/reuse, reusable sections and adaptive polling.
- [x] 2.7 Add scalar fast paths with BSON differential coverage, preserve driver TCP delivery through the byte relay, freeze its observer policy and deduplicate public integrity-digest exclusions.
- [x] 2.8 Move shared-cache relay I/O outside the Python GIL with bounded buffers, owned descriptors, exact byte counters, half-close preservation and pause/stop coverage.
- [x] 2.9 Reuse guarded namespace contexts and fixed integer BSON envelopes; retain interrupted-acquisition cleanup, scalar/subclass semantics, exact wire compatibility and malformed-key rejection.

- [x] 2.10 Classify default integer identity reads once while retaining bound-session/read-profile checks, metadata and collation eligibility, codec normalization and read-through/admission authorities; cover sync/async policy bypasses and stabilize the existing eligible-index Hypothesis example.

- [x] 2.11 Admit through native control queues independently of data sockets, retaining closed/detached rejection and single-frame socket fallback; retain each view's portable default wire shape and preserve native codec/key bypasses.

## 3. Evidence

- [x] 3.1 Record the complete version 7 study and profiles, retaining its failed miss bounds.
- [x] 3.2 Collect every version 8 phase from clean commits and record its decision under the unchanged protocol.
- [x] 3.3 Collect fresh registered evidence that passes every required issue #272 bound under the runtime decision from [issue #278](https://github.com/alessio-locatelli/client-query-cache/issues/278); versions 8 and 10 through 14 do not meet acceptance. Use the version 15 registration with direct control-queue admission and fresh baseline qualification.
- [x] 3.4 Commit the candidate declaration and version 15 baseline-only calibration protocol, qualify fresh rates without candidate observations, then record complete phase results and reproduction commands.

## Code Quality

- [x] 4.1 Scan entire edited test files for the AGENTS.md Writing Tests guidelines, including parametrization.
- [x] 4.2 Prose restriction is inapplicable: implemented by OpenAI Codex.
- [x] 4.3 Complete the configured review of the whole branch, including the final registered evidence, before spec sync and archive.
