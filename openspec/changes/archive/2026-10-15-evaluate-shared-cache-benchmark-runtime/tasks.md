# Tasks

## 1. Study definition and tooling

- [x] 1.1 Commit `reports/shared-worker-cache/runtime/plan.md` before executing alternative comparisons; use its requirements as the decision criteria.
- [x] 1.2 Add `scripts/analyze_shared_cache_runtime.py` to reproduce the planned accounting, retrospective analysis and simulations; verify its numerical behavior against constant effects, known order-statistic moments and the existing bootstrap on a small reference case.

## 2. Investigation

- [x] 2.1 Execute the bounded study with retained version 7/8 reports, preserving hashes and experimental wall time in untracked output.
- [x] 2.2 Publish `reports/shared-worker-cache/runtime/results.md` with runtime/precision comparisons, active-write alternatives, coverage constraints, a recommendation and explicit limits on optimality claims.

## 3. Empirical continuation

- [x] 3.1 Add stage timers, ordered request traces and memory observations around existing benchmark windows; preserve fresh worker/cache lifecycles and verify instrumentation with a short real-server run.
- [x] 3.2 Execute the committed discovery design, select a faster protocol against the precision requirements, then freeze a separate validation design before fresh validation measurements.
- [x] 3.3 Validate the selected protocol, quantify the complete-study cost frontier and publish the resulting preregistration or an evidence-backed minimum for the retained requirements.

## Code Quality

- [x] 4.1 Resolve PR #281's qualification provenance, environment and completion findings with regression coverage; update the qualification result contract and preregistration.
- [x] Scan edited test files against the Writing Tests guidelines.
