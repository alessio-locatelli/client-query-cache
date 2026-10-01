# Tasks

## 1. Public cache inspection and reason accounting

- [ ] 1.1 Add `BypassReason`, frozen `BypassReasonCount`, and immutable `CacheSnapshot.bypass_reasons` in the shared snapshot/statistics layer per design D2. Keep no-argument advanced `record_bypass()` as `unspecified` and leave oversized accounting separate. Extend `tests/core/test_manager_state_machine.py` or the existing core statistics behavior tests with parametrized recording cases and a real concurrent snapshot invariant: reason sums equal ordinary aggregate totals, and oversized recordings change neither.
- [ ] 1.2 Add synchronous `snapshot`, `stream_cost_snapshot`, and `active_stream_cost_databases` delegates to both managers and export their result/reason types through the three public packages. Add manager tests showing identical observations to the core, no activation/network I/O on inspection, post-close inspection, and no await for asyncio inspection. Update the corresponding API-reference/architecture statistics examples in the same part; verify public-only type imports and documented calls against both managers.

## 2. Classified eligibility and database health

- [ ] 2.1 Refactor pure request classification into shared logic and replace the existing collection/core ordinary bypass recording calls with the reason precedence in design D3. Preserve aggregate recording sites, including aliases and raced admissions. Parametrize sync/async public read tests over session/profile/options/unsafe/key cases, and compare aggregate outcomes with the pre-change baseline for sequences where several core records occur during one request.
- [ ] 2.2 Preserve distinct missing/view/time-series/inconclusive collection-probe outcomes in `_core/collection_metadata.py` and both managers' internal eligibility results while retaining public boolean eligibility behavior. Add behavior tests in `tests/core/test_collection_metadata.py` and both collection-type test modules showing reason accuracy and unchanged rechecks after absence, metadata failure, and namespace changes. Update bypass guidance with the implemented vocabulary and verify it matches snapshot observations.
- [ ] 2.3 Add local health snapshots to both coordinators/managers, retaining a fixed unsuccessful-startup status even when startup does not retain a supervisor. Add tests in both stream/manager test modules for untouched databases, startup failure, retry success, reconnect, inspection during activation, and shutdown. Verify inspection never starts a stream and cannot deadlock with cache/lifecycle locks. Document health states and explicitly distinguish health from per-write catch-up.

## 3. Optional metrics and consumer adoption

- [ ] 3.1 Introduce the minimal typed statistics-source interface and accept both managers and `CacheCore` in `register_cache_metrics` while retaining the `cache_core` keyword. Add the separate by-reason counter and preserve existing instrument identities. Extend `tests/test_otel.py` and `tests/test_docs_otel_example.py` for both manager variants, advanced positional/keyword calls, reason totals/cardinality, read-only callbacks, and the existing missing-extra behavior. Update the metrics guide with the manager-based call.
- [ ] 3.2 Update the delivered examples and README statistics calls to use manager snapshots; replace `CacheCore` annotations used only for reporting with the appropriate public manager/snapshot types. Verify each existing example still attributes hits to its own selected read shapes, retains raw writes and ownership, and passes the existing example subprocess/type-check paths. Add one final-behavior Unreleased entry.

## 4. Resource evidence

- [ ] 4.1 Compare the existing hit workloads and focused diagnostics harness against the pre-change revision after cheap checks pass. Measure reason recording, concurrent snapshots, missing-collection/session bypasses, and metric callbacks as described in D5. Record commands, latency/allocation deltas and the observed bottleneck in the implementation commit body; verify raw outputs remain untracked and no new inspection/hit path performs database I/O.

## 5. Code Quality

- [ ] 5.1 Scan the entire file for each edited or added test, including pre-existing tests, and apply the AGENTS.md Writing Tests rules, especially parametrization and public-behavior coverage. Verify there are no helper-only tests or duplicated setup/cleanup.
- [x] 5.2 If you are Claude Code, confirm that no new prose was added to code; OpenAI Codex is exempt. Not applicable: these planning artifacts were authored by Codex.
