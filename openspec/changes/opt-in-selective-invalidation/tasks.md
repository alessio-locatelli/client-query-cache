# Tasks

## 1. Configuration and proof preparation

- [ ] 1.1 Implement D1's common policy type, validation, snapshots, exports, and constructor wiring. Add parametrized sync/async constructor and collection-access tests in the existing manager test modules for the `Collection policies are immutable constructor configuration` scenarios. Update the constructor reference in the same part; verify examples use the actual exported type and signature.
- [ ] 1.2 Implement D4's common classifiers and connect them to existing prepared-read structures. Add parametrized classifier tests and Hypothesis properties for conjunction permutations, dependency unions, BSON type distinctions, and unsupported shapes. Record the exact supported subset in the API reference per D7; verify unsupported classification preserves the prior read eligibility result.

## 2. Production guards and stream routing

- [ ] 2.1 Extend the common pipeline builder and both supervisors/coordinators per D1 and D5. Add router and pipeline tests in `tests/core/test_stream_events.py` and the execution-model stream modules, comparing disabled output with the existing projection and exercising mixed policies, reopen, telemetry modes, and boundary hints. Document the hint format in `docs/development/selective-invalidation.md`.
- [ ] 2.2 Implement D2 and D3 in the common core, contracts, entries, namespace state, and eviction/publication callbacks. Extend `tests/core/test_manager_state_machine.py` with selective operation ordering; add deterministic fault injection around physical insertion, reference publication, replacement, fallback-to-selective transitions, and slot reuse. Add a barrier-controlled concurrent acquisition test for the final capacity slot across namespaces, parametrized over `max_entries=None` and a finite limit, plus lock-order tests for discard/publication paths. Verify the cache-core delta and `Selective guards preserve continuity and bounded ownership`, including ordinary advanced-core writes without hints. Record ownership and lock ordering in the maintainer guide.
- [ ] 2.3 Wire count adapters, final find preparation, and `CursorCapture` in both execution models to the shared guard APIs. Extend `tests/test_cached_cursors.py`, `tests/test_retention_reads.py`, and execution-model read tests for the cached-read-api delta and D3's release paths. Add separate sync/async regressions for partial consumption followed by dropping the cursor without close, `gc.collect()`, and a new capacity acquisition; verify reclamation and no partial admission, including after drop/recreate. Exercise collection while storage locking is active to catch finalizer re-entry; retain separate explicit-close and cancellation tests. Verify captured query data cannot be changed by caller mutation before admission. Deliver D7's usage guide, update the affected existing guides and Context7 rules, and exercise both public examples against the integration fixture.

## 3. Real-server integration qualification

- [ ] 3.1 Add a parametrized real-server matrix across sync/async and the four policy combinations, using existing replica-set fixtures. Cover every scenario in the selective-invalidation and projection deltas; include boundary UTF-8 lengths/name counts, numeric cross-types, `ObjectId`, Boolean separation, arrays, null/missing, collation defaults/overrides, hinted sparse/partial-index counts, nested paths, expanded ambiguous-path metadata, and unsupported operators. Use native reads and drained event positions as the oracle, then verify exact/prefix/count driver-command counts and absence of extra streams/lookups. Link the supported and fallback cases from the maintainer guide to these tests.
- [ ] 3.2 Extend existing recovery and admission-race integration tests for selective entries, including interrupted/resumed streams, history loss, database drop, rename, drop/recreate, index events, manager close, and cancellation. Verify ordinary identity and generic-query behavior in the same mixed-policy database, and distinguish permitted pre-event stale reads from incorrect post-event retention using the existing event-drain helpers.

## 4. Production performance acceptance

- [ ] 4.1 Add D6's production runner mode and focused cell selection to the reusable research workload infrastructure. Preserve historical experiment reproduction and add a small qualification test proving production mode uses public managers and reconciles native commands, cache outcomes, event counts, and oracle results. Provide the exact bounded reproduction commands in the maintainer guide.
- [ ] 4.2 Execute D6's matched comparisons and memory controls, including the ordinary existing test-duration comparison. Retain the concise production evidence and measured bottleneck in the maintainer guide. Keep raw results local. Resolve reproducible slowdowns or record the maintainer's explicit approval before marking this task complete; unresolved noise cannot support an acceptance claim.

## 5. Code Quality

- [ ] 5.1 Scan every edited or added test file in full, including its pre-existing tests, and apply the `AGENTS.md` Writing Tests guidelines, including parametrization; verify no duplicated cases or test-helper coverage scaffolding remains.
- [ ] 5.2 Confirm no new code prose was added if applying as Claude Code; OpenAI Codex is exempt.
