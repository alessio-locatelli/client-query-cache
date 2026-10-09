# Tasks

## 1. Baseline evidence

- [x] 1.1 Implement design.md's "Reuse the benchmark package with spawned workers", "Freeze a small baseline protocol", and "Register event-count lag captures" in `benchmarks/stream_cost/multiprocess_run.py`, with the frozen configuration and direct development dependency declaration described there. Add benchmark tests for aggregate schedule partitioning, stream-only/control workload equivalence, child-owned clients and metrics, startup failure, stream counts, required metric failures, complete capture/separation counts, and bounded cleanup. Create the canonical research document with verified setup and runner instructions; verify a local smoke run reports distinct worker and harness measurements.
- [x] 1.2 Run the registered baseline with `uv run -- python -m benchmarks.stream_cost.multiprocess_run --output benchmark-reports/shared-invalidation/baseline.json`. Implement design.md's "Gate the prototype on removable stream cost", extending `await_statistics.py` as specified; verify exact-enumeration weights, signed bounds, preservation of existing log-statistic results, an active-only opportunity, and complete/below-threshold/inconclusive outcomes with benchmark regression tests. Record the baseline outcomes and gate decision in the research document, with the measured revision and reproduction configuration hash.

## 2. Conditional prototype

Tasks 2.1–2.3 are completed by the conditional skip rule: the registered gate did not pass. See [baseline result](../../../../docs/development/research/shared-invalidation-feasibility.md#baseline-result) for the evidence and scope.

- [x] 2.1 Implement the receiver state and local read/admission driver from design.md's "Model delivery at the cache-core boundary" in `benchmarks/stream_cost/shared_invalidation.py`. Add parametrized fault tests plus Hypothesis operation-ordering tests over real `CacheCore` instances for the delta's uncertainty and recovery scenarios; verify both read shapes reject admissions spanning recovery. Document the observed state transitions in the research reference.
- [x] 2.2 Add the coordinator, bounded IPC, and independent-stream research variant described in design.md. Add real-replica-set tests covering every listed delivery fault with sync, asyncio, and mixed subscribers; verify one coordinator stream serves the shared group, healthy local lookups issue no IPC/database calls, and a stalled subscriber leaves the other subscribers progressing. Record transport and lifecycle observations in the research reference.
- [x] 2.3 Extend `multiprocess_run.py` with `--phase prototype` and implement design.md's "Decide prototype benefit per group and workload" and exact lag intervals from "Register event-count lag captures". Regression-test capture completeness, endpoint subtraction, uncertainty margins, recommendation-level correction, and rejection of any failing safety component. Run the frozen experiment with a new output path; verify identical research receivers and complete resource accounting, then record every scoped recommendation, failure, and native-manager integration limitation in the research reference.

## 3. Feasibility recommendation

- [x] 3.1 Finish the canonical research reference and link it from `docs/development/index.md`. Resolve the assessment entries in design.md's transport table and fallback discussion, applying the delta's evidence-limits contract. Verify that its commands reproduce the retained conclusions, including an explicit prototype skip when applicable, and that each unresolved product question links to issue #87 rather than becoming an unowned follow-up.

## 4. Code Quality

- [x] 4.1 Scan the entire file for each edited or added test, including pre-existing tests, and verify compliance with the "Writing Tests" guidelines in `AGENTS.md`, including parametrization.
- [x] 4.2 Confirm that no new prose was added to code if applying as Claude Code. OpenAI Codex is exempt; reconsider this completion marker if another agent applies the change.

## 5. PR review corrections

- [x] 5.1 Reject stopped receivers, idle watching workers without observed polling, and unsuccessful child cleanup; cover the receiver and shutdown failures with regression tests.
- [x] 5.2 Collect spawned-worker coverage with the supported coverage.py integration, exercise meaningful missing benchmark behavior, and pass the repository's complete coverage gate without weakening its threshold.
- [x] 5.3 Restore the report's measurement provenance through reachable equivalent source revisions and retain concise derived block-rate summaries; audit the retained idle samples against the added polling check.
- [x] 5.4 Place argument constraint comments beside their arguments and audit inline comments in the changed Python files after formatting.
- [x] 5.5 Isolate calibration test clocks from driver threads and give instrumentation-only integration tests scheduling slack under coverage; retain the registered benchmark protocol and explicit lateness rejection test.
- [x] 5.6 Gate delayed delivery on the actual application-window end, let failed children finish cleanup within the existing deadline, and allow forced-shutdown tests enough time to save coverage before escalation.
- [x] 5.7 Enforce the idle polling-gap contract with monotonic command timestamps, add continuous and stalled-poll regressions, and update the report's retrospective evidence limits.
- [x] 5.8 Retain thread coverage alongside multiprocessing and restore the short forced-shutdown test budget; verify complete coverage without lost child measurements.
