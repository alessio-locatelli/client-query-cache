# Tasks

## 1. Prepare time-efficient experiments

- [ ] 1.1 Prepare the D3 selected-workload runner and stopping controls, reusing existing research tooling; verify one justified baseline/A/A smoke acquisition completes with valid outcomes and reports its planned and actual duration. Initialize the D4 evidence record with the frozen main revision, D3 comparison-family registration and per-benchmark duration justifications before acquisition.

## 2. Formatting and existing dependency reuse

- [ ] 2.1 Prototype D1 candidate 1a at each site separately; extend `array/tests.rs` and the relevant `tests/core/test_keys.py` cases for D1's boundaries, run the bounded comparison, and integrate each qualifying site or restore it. Record both site decisions in D4 evidence.
- [ ] 2.2 Audit the origins of candidate 1b's keys and compare eligible collections under D3; verify changed maps through shared publication/churn tests and both Python-enabled and default-feature native builds. Integrate qualifying substitutions and record exact collections and rejected ones in D4 evidence.

## 3. Hash function and table experiments

- [ ] 3.1 Evaluate candidate 2a under D2's encoding/version policy; extend `hash/tests.rs`, index attachment/collision cases, and shared-owner/reader tests to verify its invariants. Run its D3 screening and required winner confirmation, integrate only if qualified, and record deterministic hash configuration plus disposition in D4 evidence.
- [ ] 3.2 Evaluate candidate 2b with the table-only and combined comparisons in D1; verify retained variants against `tests/core/test_key_equality_classes.py` and existing key-collision/reentrancy cases. Record the independently attributable decision in D4 evidence and remove rejected variants.

## 4. Replace custom storage bookkeeping where justified

- [ ] 4.1 Screen and, if compatible, prototype candidate 3a; add operation-order cases to `tests/shared_cache/test_owner.py` or adjacent native tests covering D1's probe invariants. Deliver its complexity comparison, protected-work assessment and focused owner-contention measurements from D3 in D4 evidence, retaining only a qualifying replacement.
- [ ] 4.2 Screen candidate 3b's reservation mapping before substitution; if viable, verify handle reuse, churn, namespace recreation, close and empty-storage reclamation using existing cache lifecycle and `tests/memory/test_cache_churn.py` cases. Record its D1 storage comparison and accept/reject outcome in D4 evidence.

## 5. Allocation and synchronization screens

- [ ] 5.1 Sample candidate 4a's real list lifetimes and length distribution, then compare a justified inline capacity under D3 if the screen supports it. Verify equal key-sizing/admission decisions for shallow and spilling keys; retain the chosen representation or the existing vector and record why in D4 evidence.
- [ ] 5.2 Inventory candidate 4b's locks and panic/poison paths; apply D2's compatibility screen before prototyping. If any lock remains eligible, verify panic behavior and shared-manager concurrency plus its D1 contention comparison. Record each selected lock's outcome or the concrete reason for rejection in D4 evidence.

## 6. Combined production result

- [ ] 6.1 Compare the final installed release build with frozen main using D3's combined controls and qualification confirmations, measuring unchanged existing-test execution separately from added tests where affected. Resolve adverse signals under the existing regression policy and finish D4's per-candidate and combined decisions, including an explicit outcome if none qualifies.
- [ ] 6.2 Remove unsuccessful dependencies, experimental adapters and orphaned code; verify retained benchmark commands use production interfaces or compile-time-only tests, using D4's stable-source reconstruction procedure for retained experiments. Update `docs/development/native-quality.md` only for lasting measurement/compatibility guidance established by the accepted work, and verify D4's retained reconstruction commands in a fresh checkout without relying on pre-merge refs.

## 7. Code Quality

- [ ] 7.1 Scan every entire file containing edited or added tests, including its pre-existing tests, for compliance with the AGENTS.md Writing Tests guidelines, including parametrization; correct applicable findings.
- [ ] 7.2 If the implementing agent is Claude Code, confirm that no new prose was added to code; OpenAI Codex is exempt.
