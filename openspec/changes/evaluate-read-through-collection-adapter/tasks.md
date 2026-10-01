# Tasks

This study modifies no runtime behavior and declares `skip_specs: true`. Experiment code and raw results remain untracked under `/tmp`; the durable report is `docs/read-through-collection-adapter-evaluation.md`. Either a supported go recommendation or a concrete no-go completes the study without authorizing a production adapter.

## 1. Versioned consumer contract

- [ ] 1.1 Verify requests-cache 1.3.3, Celery 5.6.2 and py-abac 0.4.1 source revisions against the delivered integrations, and select/verify a published Eve release or reuse the active examples change's verified selection. Populate the report with exact reads, cursor calls, writes/admin operations, options, ownership, construction hooks and concrete-type assumptions. Verify each matrix row cites the released source and a consumer symbol; record environment blockers without upstream repairs.
- [ ] 1.2 Capture the explicit-view baseline: identify each copied upstream conversion/validation override in the three delivered examples and Eve's required adapter surface. Reproduce selected consumer reads with attribution to cache-hit statistics. Record reproduction commands and which paths are intentionally uncached; verify completed-result caches in Celery or other upstream caches cannot masquerade as library hits.

## 2. Isolated adapter experiments

- [ ] 2.1 Prototype the bounded composed collection/cursor protocol in `/tmp` and compare it with a cursor-preserving alternative and the explicit-view baseline. Preserve raw writes and manager/client ownership without temporary receiver swaps or shared-client monkeypatches. Exercise each delivered consumer's selected conversion path with no copied read conversion where feasible; record whether the adapter actually eliminates those overrides. Verify required native cursor return/call timing, including asyncio `find`, and positive/negative static typing/source-navigation cases without dishonest casts/stubs.
- [ ] 2.2 Exercise required sorting, pagination, projection, batch behavior, close/context cleanup, partial consumption, iteration errors, clone/rewind where used, unsupported modes and concurrent writes. For any cache candidate, capture original generations and admit only a complete result still passing guards. Record decisive traces in the report; verify abandoned, cancelled, errored or invalidated results are never admitted and writes/admin calls remain raw.
- [ ] 2.3 Prototype bounded extra cache buffering with small/large result sets and oversized single documents. Stop retaining cache candidates at the admission limit while continuing to stream complete results. Measure driver batches, consumer-owned output and extra cache/encoding memory separately; record first-item/full-result latency, CPU, allocations and network calls against raw and materialized baselines. Verify results are complete when caching is declined and raw measurements stay untracked.

## 3. Feasibility decision

- [ ] 3.1 Complete the report with pinned sources, a minimal reproducible experiment listing and exact run commands, concise measurements, topology/environment limits, truthful support/typing contracts, wrapper-upgrade maintenance and the observed bottleneck. Apply every go/no-go gate in design D4; explicitly record Eve limitations instead of claiming unverified compatibility. Verify another developer can reproduce the result without relying on a temporary path or conversational context.
- [ ] 3.2 Record one final go/no-go recommendation. A go enumerates the exact independently implementable production contract and remaining support limits; a no-go names the failed gates and retains explicit views. Verify neither outcome changes public API/docs/examples, dependency manifests, workflows, submodules or upstream code, and no pending implementation work is added to this study's checklist.

## 4. Code Quality

- [x] 4.1 Scan the entire file for edited/added tests and apply AGENTS.md Writing Tests rules, including parametrization. Not applicable: this study adds no repository test files; its reproducible experiments are evidence for the report.
- [x] 4.2 If you are Claude Code, confirm that no new prose was added to code; OpenAI Codex is exempt. Not applicable: these planning artifacts were authored by Codex.
