# Tasks

## 1. Measurement foundation

- [x] 1.1 Clarify `stream_polls` as manager iteration calls in telemetry labels and relevant documentation; verify existing sync and async counter tests still describe the observed count accurately.
- [x] 1.2 Add an isolated await-time benchmark that observes actual `getMore` commands and requested `maxTimeMS`, captures idle CPU and direct-path bytes, and retains no command bodies; verify instrumentation with a real replica-set run and tests that distinguish one `next()` call from multiple `getMore` commands.
- [x] 1.3 Add matched idle, paced-write, burst-write, and idle-shutdown windows for sync and async managers, with fresh state and counterbalanced repetitions; verify report validation rejects missing measurements, unequal schedules or events, and mismatched topology.

## 2. Default decision

- [x] 2.1 Freeze and review a versioned pre-run configuration before taking any samples, including candidate order, six blocks, window durations, write schedules, shutdown trials, one-sided paired-block bounds with 95% family-wise coverage and Holm-Bonferroni adjustment, denominator resolution rule, and all selection gates from `design.md`; verify decision tests reject altered configuration hashes and choose by decisive results in both execution models, then shorter wait.
- [ ] 2.2 Run the frozen matrix, validate and retain its per-candidate decision evidence with the configuration hash, revision, and environment, and select the default strictly from that evidence; verify the retained report passes its validator and identifies every candidate's server and client CPU, bytes, latency, and shutdown outcome.
- [ ] 2.3 Document the chosen value, measured rationale, timeout and topology limits, and a link to retained evidence in `docs/stream-cost-benchmarks.md`; verify every numerical claim against the report and reproduce the benchmark command from the documented configuration.

## 3. Public configuration

- [ ] 3.1 Add one shared selected default and positive-integer validation, then thread an optional per-manager `max_await_time_ms` through synchronous and asynchronous coordinators to initial and reopened streams; verify parametrized tests cover omission, two managers with different overrides, reconnects, booleans, invalid numbers, and range limits.
- [ ] 3.2 Verify representative real-server sync and async event delivery, interruption/recovery, and in-flight shutdown with the selected default and at least one larger override; resolve any failure against the existing coherency contract before accepting the default.
- [ ] 3.3 Document the manager argument and its timeout interaction in `docs/api-reference.md`, update the README's public usage guidance only where needed, and add one final-behavior changelog entry; verify documented constructor examples run with the public API.

## 4. Code Quality

- [x] 4.1 Scan every edited or added test file in full, including pre-existing tests in those files, for the `AGENTS.md` Writing Tests guidelines; verify repeated cases use parametrization and cleanup is outside test bodies.
- [x] 4.2 Confirm no new prose was added to code under the Claude Code rule (inapplicable: this change is planned for OpenAI Codex).
