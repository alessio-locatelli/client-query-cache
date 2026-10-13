# Tasks

## 1. Registration and planning

- [x] 1.1 Add v6 timing applicability and fault-cell planning; test missing metadata, all cases and repetitions, and frozen v4/v5 rejection.

## 2. Scripted trials

- [x] 2.1 Add fault worker controls and the scenario driver using existing owner controls and reusable safety oracles; verify all registered scenarios against a disposable replica set with both execution models.
- [x] 2.2 Integrate event-relative records into the runner and window dispatch, preserving failed trials; test event origins, unavailable intervals and safety failures.
- [x] 2.3 Handle a broken-pipe error propagated to the asyncio RPC reader during owner exit; replay the observed failure in a deterministic regression and repeat the registered phase without unhandled reader tasks.

## 3. Analysis and evidence

- [x] 3.1 Add complete-matrix fault analysis and readiness gating; test boundary, missing, duplicate and unsafe evidence. Document the invocation and timing interpretation in the research guide.
- [x] 3.2 Execute the registered phase and record a concise results summary with reproduction commands and raw outputs untracked.

## 4. Review corrections

- [x] 4.1 Verify fencing across the complete hot set and both cache selection paths; add regressions for non-first-key residency and RPC hits.
- [x] 4.2 Distinguish graceful restart, owner failure under continuous local reads, and explicit reattachment; verify traffic across pause and kill transitions.
- [x] 4.3 Bound retained observations, restrict exhaustive residency checks to detection and rewarming, and reuse the existing retry delay after asynchronous RPC timeouts.
- [x] 4.4 Repeat the registered phase and replace the insufficient safety evidence with corrected results.

## 5. Recovery safety and traffic reuse

- [x] 5.1 Retain first-hit evidence independently of readiness; validate recovery hits against worker eligibility and owner readiness-window timestamps, including transitions between samples.
- [x] 5.2 Prepare direct local-index lookup inputs once per traffic session and measure the change.
- [x] 5.3 Repeat the registered phase and replace the prior recovery evidence.
- [x] 5.4 Remove a connection only after its handover descriptors and socket have closed, resolving the cleanup-observation race found during full validation.

## 6. Code Quality

- [x] 6.1 Check entire edited test files against the repository test guidelines.
- [x] 6.2 Claude-specific prose restriction is inapplicable to Codex.
