# Tasks

Runtime tasks in sections 2-4 are blocked until 1.4 passes. File-existence status is not that proof. If no supported public mechanism meets the design/spec constraints, document the concrete blocker, leave runtime tasks open, and stop without weakening the guarantee.

## 1. Causal progress proof

- [ ] 1.1 Establish a supported immutable boundary from acknowledged explicit-session writes and committed transactions on the manager's deployment. Inspect the pinned PyMongo public session/change-stream APIs and official MongoDB ordering documentation; distinguish operation time, cluster time and opaque resume tokens. Write the provenance/write-concern/topology argument in `docs/causal-invalidation-barrier-proof.md` and reproduce accepted/rejected inputs against a disposable server. Verify no live session is shared with the stream worker and no unacknowledged/uncommitted/foreign input is accepted.
- [ ] 1.2 Build an untracked public-API experiment under `/tmp` that relates the boundary to fully applied database-stream progress. Test same-timestamp events, multi-document transactions, different collections, no-op writes, an idle database, filtered events and sharded ordering with both execution models. Record pinned versions, minimal reproducible source/commands and decisive traces in the proof report. Verify quiet-stream completion without marker writes, token decoding, private driver hooks or unrelated later application writes; record a blocker if this cannot be established.
- [ ] 1.3 Extend the experiment with resumable reconnect, history loss, drop/recreate, reads spanning invalidation, simultaneous waiters, activation timeout, cancellation and shutdown. Measure additional round trips/getMore traffic, normal hit overhead, retained progress/waiter memory, latency and cleanup bounds. Record concise results and the observed bottleneck in the proof report; verify raw output stays untracked and the proof covers both advertised topologies.
- [ ] 1.4 Update this change's design and tasks with the proven mechanism, exact public signature, boundary representation, exported exceptions, write-concern requirements, complete-frontier ordering and deadline/cleanup behavior. Obtain another required review of those substantive edits. Verify the reviewed mechanism satisfies every delta scenario and introduces no scope expansion before releasing runtime tasks; otherwise report the specific unmet constraint and stop.

## 2. Progress publication and failure boundaries

- [ ] 2.1 After 1.4, implement the selected shared boundary/continuity representation and coordinator progress publication in both stream variants, publishing only after all relevant invalidations are applied. Land focused stream tests in the same part for equal-timestamp ordering, filtered batches, grouped transactions and in-flight admissions. Verify no receive/token-save action alone releases a waiter, and document the implemented progress semantics in the proof report.
- [ ] 2.2 Implement the reviewed continuity rules for reconnect, history loss, invalidation and shutdown. Land corresponding sync/async stream tests that distinguish suspension from proof loss, explicitly fail affected waits after loss, and prevent reopening on shutdown. Verify existing recovery/read-bypass semantics and one permanent stream per database are preserved.

## 3. Public bounded waits

- [ ] 3.1 Implement the reviewed manager API, exported boundary/errors and input validation. Use the single monotonic deadline over activation/acquisition/waiting and native sync condition/event versus asyncio waiter primitives. Land manager tests for invalid timeouts, unsupported/foreign boundaries, closure, timeout during activation and cancellation of one among multiple waiters. Verify no completed/cancelled waiter state accumulates and no shared application session is used concurrently. Update API-reference construction/method/error guidance in this part with the exact implemented contract.
- [ ] 3.2 Land disposable real-server tests for document/query invalidation through explicit write/commit boundaries, no-op/idle completion, transaction groups and independent later writes, in both models and supported topologies. Verify successful return rejects old cache entries/admissions while later independent writes retain eventual semantics. Update architecture consistency guidance and only those delivered examples where a real supported boundary is obtainable; otherwise retain honest consumer polling. Add one final-behavior Unreleased entry.

## 4. Resource evidence

- [ ] 4.1 Re-run the proof workload against final runtime code and the pre-change supervisor/hit baseline after cheap checks pass. Record commands, barrier latency, idle traffic, round trips, allocations, many-waiter contention and normal-hit overhead in the implementation commit body. Verify the implementation meets the reviewed resource bounds, retains no per-write history, and tracks no raw measurement payloads.

## 5. Code Quality

- [ ] 5.1 Scan the entire file for each edited or added test, including pre-existing tests, and apply AGENTS.md Writing Tests rules, including parametrization and Hypothesis for real operation-ordering invariants. Verify fixtures own cleanup and no helper-only tests or impossible mocked scenarios substitute for the proof.
- [x] 5.2 If you are Claude Code, confirm that no new prose was added to code; OpenAI Codex is exempt. Not applicable: these planning artifacts were authored by Codex.
