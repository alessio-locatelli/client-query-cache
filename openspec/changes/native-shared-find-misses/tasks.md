# Tasks

## 1. Native family selection

- [x] 1.1 Implement the native selection design and bindings in `native/shared-index/src/{index,python}.rs`; cover exact/covering/unlimited selection, collisions, directory/payload reuse, empty-family reclamation and completeness failure/recovery in native tests and Loom. Add a reproducible floor diagnostic under `research/` for 1, 8 and 64 limits per family; retain all results and stop integration if lookup/maintenance costs invalidate the design.
- [x] 1.2 Integrate `IndexPublisher` with the native operations and unpublished-entry accounting; extend `tests/shared_cache/` differential operation sequences through publication refusal, eviction, writes, resets and recycled namespace slots. Document the publication/completeness invariants in `docs/development/shared-cache.md` alongside the implementation.

## 2. Local cursor admission

- [x] 2.1 Adapt sync/async shared cursors, capture ownership and authenticated owner admission to the design; extend adapter/owner tests to prove no selection RPC for complete absence, compatible cross-worker hits and one family serialization per cold query. Exercise the existing socket-only fallback and queue saturation paths.
- [x] 2.2 Extend real-process sync/async cursor tests for partial consumption, close, error/cancellation, oversized results, write-after-token-validation, progress recovery and owner restart; verify no stale publication or retained owner capture. Update the canonical shared-read guide and affected Context7 rule only where the resulting documented behavior changes.

## 3. Current-release evidence

- [ ] 3.1 Execute the implementation comparison in `reports/shared-worker-cache/current-costs/plan.md`, using installed clean release wheels for main and candidate with the same locked dependencies. Complete `results.md` with resources, cache outcomes, attribution, alternatives, negative results, source revisions/digests and reproduction commands; investigate each reproducible regression before accepting implementation.
- [ ] 3.2 Compare existing affected tests against main separately from new tests, using three alternating pairs of the unchanged test selection and reporting elapsed-time ranges. Keep raw logs untracked and audit all diagnostic output for failures/warnings.

## 4. Code Quality

- [x] 4.1 Scan each entire edited test file, including pre-existing tests, against the `AGENTS.md` Writing Tests guidelines and consolidate repeated cases with parametrization.
- [x] 4.2 The Claude-only prose restriction is inapplicable: this change is prepared by OpenAI Codex.
