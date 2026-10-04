# Tasks

## 1. Hit workload calibration

- [x] 1.1 Measure the 256-hit baseline for synchronous/asynchronous hits and small/medium profiles in six fresh processes each; keep raw results untracked.
- [x] 1.2 Set the shared hit count in `guard_workload.py` to 2,048, repeat the same measurements, and verify every block exceeds 5 ms while existing cache-outcome assertions and guard tests pass.
- [ ] 1.3 Record the before/after duration ranges, added timed work, environment, and reproduction command in the implementation commit body.

## 2. Code Quality

- [x] 2.1 Check edited test files against the Writing Tests guidelines; confirm whether any test edits are needed.
- [x] 2.2 Confirm the Claude-only prose restriction is inapplicable to this Codex implementation.
