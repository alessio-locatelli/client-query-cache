# Tasks

## 1. Registration and planning

- [x] 1.1 Add v6 timing applicability and fault-cell planning; test missing metadata, all cases and repetitions, and frozen v4/v5 rejection.

## 2. Scripted trials

- [x] 2.1 Add fault worker controls and the scenario driver using existing owner controls and reusable safety oracles; verify all registered scenarios against a disposable replica set with both execution models.
- [x] 2.2 Integrate event-relative records into the runner and window dispatch, preserving failed trials; test event origins, unavailable intervals and safety failures.
- [ ] 2.3 Handle a broken-pipe error propagated to the asyncio RPC reader during owner exit; replay the observed failure in a deterministic regression and repeat the registered phase without unhandled reader tasks.

## 3. Analysis and evidence

- [x] 3.1 Add complete-matrix fault analysis and readiness gating; test boundary, missing, duplicate and unsafe evidence. Document the invocation and timing interpretation in the research guide.
- [ ] 3.2 Execute the registered phase and record a concise results summary with reproduction commands and raw outputs untracked.

## 4. Code Quality

- [x] 4.1 Check entire edited test files against the repository test guidelines.
- [x] 4.2 Claude-specific prose restriction is inapplicable to Codex.
