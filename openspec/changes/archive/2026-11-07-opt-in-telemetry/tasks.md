# Tasks

Use the [telemetry-control contract](specs/telemetry-control/spec.md) and the [design](design.md), including its validation constraints.

## 1. Configuration and inspection boundaries

- [x] 1.1 Implement [Carry policy through existing configuration](design.md#carry-policy-through-existing-configuration). Add parametrized configuration and descriptor round-trip cases covering defaults, invalid types and both valid modes; update the API and shared configuration tables.
- [x] 1.2 Apply [Diagnostic access rejects disabled collection](specs/telemetry-control/spec.md#requirement-diagnostic-access-rejects-disabled-collection) to managers, advanced cores, stream coordinators and the owner request handler. Cover every diagnostic method, disabled owner requests with an endpoint that fails if called, and enabled post-close behavior in `tests/core/`, `tests/shared_cache/test_diagnostics.py` and both manager test suites. Document the errors in `docs/user/operations/monitoring.md` and the API error table.

## 2. Cache operation producers

- [x] 2.1 Apply [Guard producers before preparing observations](design.md#guard-producers-before-preparing-observations) to the Python-core and shared-adapter rows of the audit. Adapt existing counter tests to opt in locally. Add disabled-mode read/admission/eviction cases with recording and diagnostic-log preparation hooks that fail if invoked; keep admission, invalidation and retention assertions independent of snapshots.
- [x] 2.2 Apply the same decision to `LocalCacheCore` and `SharedOwnerCore`. Add native functional cases for both policies; verify real results, capacity limits, alias behavior and invalidation in default mode without diagnostic access. Update native binding tests and protocol stubs with the changed setup contract.

## 3. Streams and owner supervision

- [x] 3.1 Apply the stream portion of [Separate supervision from measurement](design.md#separate-supervision-from-measurement). Extend `tests/core/test_stream_events.py`, `tests/core/test_stream_health.py`, both stream suites and startup fixtures: disabled cases must route events without telemetry timestamps and fail if measurement encoding, collectors or diagnostic clock functions run. Exercise reopening, startup failure, cancellation and shutdown in both modes.
- [x] 3.2 Apply that decision to the owner audit rows. Extend `tests/shared_cache/test_owner.py`, `test_diagnostics.py` and attachment recovery cases to verify disabled lease expiry, restart fencing, limits, authorization and reattachment while measurement hooks remain unused. Retain warning assertions for failure paths.
- [x] 3.3 Apply that decision to the attachment and native-ring audit rows. Extend attachment-failure, admission-queue and native-ring tests to verify full-ring behavior, one-way overflow and recovery generations in both modes; review each counter condition for embedded operational side effects.

## 4. Telemetry integration and consumers

- [x] 4.1 Implement [Apply errors at diagnostic boundaries](design.md#apply-errors-at-diagnostic-boundaries) for the OpenTelemetry adapter and update its protocols and test doubles. Extend `tests/test_otel.py` with disabled sources and a meter that fails if any instrument is created, covering both execution models and advanced sources; preserve existing enabled series assertions. Update the canonical telemetry example and `tests/test_docs_otel_example.py`.
- [x] 4.2 Find remaining diagnostic consumers with `rg 'snapshot\(|stream_cost_snapshot|stream_health_snapshot|active_stream_cost_databases|reset_stream_cost_statistics|register_cache_metrics' tests examples benchmarks docs README.md context7.json`. Set explicit opt-in only where observations are consumed; update monitoring examples, affected Context7 rules and public links. Inspect benchmark constructor propagation statically, verify runnable documentation tests and preserve ordinary examples on defaults. Apply the changelog source's editing policy to any required release note.
- [x] 4.3 Audit all production Python and Rust source after integration, including helpers outside the initial audit table. Use `rg -n 'record_|counter|statistic|snapshot|telemetry|observation|observe|perf_counter|monotonic|time\(|fetch_add|\+=' src/client_query_cache native/shared-index/src` as a starting inventory, then follow aliases and callers. Classify each remaining counter, sample, instrumentation allocation and observation-only clock read as enabled-only, operationally required, or explicitly constructed measurement tooling. Record file/symbol references and reasons in a concise Markdown audit under this change; add focused disabled-path regression cases for newly found producers. Completion requires no unclassified or default-on observation producer.
- [x] 4.4 Adapt the existing benchmark runner's observation-dependent checks to support the comparison in [Validation constraints](design.md#validation-constraints), then execute that protocol and deliver its summary. Verify the timed candidate uses the intended collection mode and the compared runs execute equivalent cache outcomes; retain rejected or incomplete pairs as limitations.
- [x] 4.5 Implement the PGO comparison in [Validation constraints](design.md#validation-constraints). Cover the training policies in `tests/test_pgo_training.py` and update the canonical native release-build guide.

## 5. Code Quality

- [x] 5.1 Scan the entire file for edited or added tests (including pre-existing tests within the file) and ensure that the Writing Tests guidelines from `AGENTS.md` are applied, including test parametrization.
- [x] 5.2 During apply, confirm compliance with the Claude-only restriction on new code prose, or mark it inapplicable if the implementing agent is OpenAI Codex.

Task 5.2 is inapplicable: the implementing agent is OpenAI Codex.
