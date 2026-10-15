# Tasks

## 1. Study definition and tooling

- [x] 1.1 Commit `reports/shared-worker-cache/runtime/plan.md` before executing alternative comparisons; use its requirements as the decision criteria.
- [ ] 1.2 Add `research/shared_cache_runtime/analyze.py` to reproduce the planned accounting, retrospective analysis and simulations; verify its numerical behavior against constant effects, known order-statistic moments and the existing bootstrap on a small reference case.

## 2. Investigation

- [ ] 2.1 Execute the bounded study with retained version 7/8 reports, preserving hashes and experimental wall time in untracked output.
- [ ] 2.2 Publish `reports/shared-worker-cache/runtime/results.md` with runtime/precision comparisons, active-write alternatives, coverage constraints, a recommendation and explicit limits on optimality claims.

## Code Quality

- [x] Scan entire edited test files against the Writing Tests guidelines: no test files planned; numerical verification belongs to task 1.2.
- [x] Claude-only prose restriction: applied by Codex.
