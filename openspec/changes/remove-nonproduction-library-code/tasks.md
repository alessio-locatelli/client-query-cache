# Tasks

## 1. Production configuration and imports

- [x] 1.1 Extract D1's production configuration into `_core/config.py`; update Python runtime/type imports, native setup, public exports, and configuration tests together. Verify public import identity and `typing.get_type_hints`, plus sync/async local and shared construction. Update affected current configuration references using public imports.
- [x] 1.2 Rename D1's production generic delegates and their native constructor fields without duplicating the implementations. Adapt existing custom-mapping/sequence, numeric, ordering, error, and codec tests; verify the native production path still invokes the required delegates and update maintainer references to their actual purpose.

## 2. Delete the Python engine and convert its consumers

- [x] 2.1 Convert core lookup, admission, retention, alias, find-compatibility, and state-machine contract cases per D3 to the production native owners. Remove reference factories, mechanics-only tests, and differential cache implementations. Verify the retained generated schedules and race/collision cases against explicit specification outcomes; update the core verification description in the maintainer guide.
- [x] 2.2 Convert event/stream fixtures, collection tests, memory tests, and current invalidation/startup benchmarks per D3. Verify real event-drain observation, sync/async behavior, native reclamation after drop/clear/close, and honest allocation/RSS accounting. Remove Python private-index assertions and update memory/benchmark command documentation with the changed measurement scope.
- [ ] 2.3 Delete D1's obsolete modules, mixed-module members, package re-exports, and orphaned imports/types after the consumer conversions. Verify no source, stub, test, script, current benchmark, or research command imports the removed engine. Update `docs/development/architecture.md` to the actual production path in the same part.

## 3. Native runtime binding cleanup

- [ ] 3.1 Remove D2's development-only bindings, Rust implementations, registrations, and stubs. Adapt affected owner/reader, key-lifetime, cursor, metadata, and shared-publication tests using production operations. Verify the native build and focused binding tests, including OS-backed errors, without replacement debug bindings; update `docs/development/shared-cache.md` and the binding inventory.
- [ ] 3.2 Adapt the retained inline native unit tests and Loom models only where D2's removed facilities affect them. Verify `just rust-tests`, `just rust-models`, and the established native coverage flow use the existing crate/module assembly, with production dead-code diagnostics enabled and no broad new exclusions. Confirm test-only helpers remain excluded from ordinary release compilation; update affected native-quality and active coverage references without relocating tests or introducing new test roots.

## 4. Tooling dependency closure

- [ ] 4.1 Adapt the shared-cache benchmark/fault harness per D3 to harness-side proxy facilities, and remove obsolete floor workloads and binding-specific tests. Verify directional byte accounting, backpressure, cancellation, pause/recovery, and resource cleanup in existing harness tests, followed by a bounded real-server qualification. Update the fault-recovery plan and current benchmark guides without changing historical result claims.
- [ ] 4.2 Remove obsolete engine/guard selectors and reference-dependent research implementations from D3's inventory. Preserve useful production workload inputs and oracles without preserving a cache engine. Verify retained CLI commands select only the production implementation and retired commands have no current documentation entry point; historical reports continue referring to their immutable source revisions.
- [ ] 4.3 Convert PGO training and its tests per D3. Verify the database-free training command exercises its complete revised scenario manifest and produces a usable profile for the cleaned extension; build/install the resulting optimized wheel with the existing non-publishing release flow. Update current release/training guidance and relevant Context7 rules.

## 5. Completion evidence

- [ ] 5.1 Complete every row of D5's distribution acceptance matrix and record separate inventories for the installed wheel and extracted source distribution. Finish the runtime consumer/dependency audit, remove orphaned implementations and bindings, and verify public behavior through both artifact installations. The evidence must distinguish compile-time-only tests/build material from runtime contents and confirm no duplicate engine, compatibility wrapper, or development-only runtime export remains.
- [ ] 5.2 Execute D6's matched production-build and retained-test comparisons. Record the measurements, uncertainty, and reproducible commands in a concise maintainer summary. Resolve reproducible regressions or obtain the explicit approval required by repository policy before completing this task.

## 6. Code Quality

- [ ] 6.1 Review every edited test file in full, including pre-existing tests, against the `AGENTS.md` Writing Tests rules and parametrization requirements; verify that removed mechanisms have not been recreated in test helpers.
- [ ] 6.2 If applying as Claude Code, confirm that no new prose was added to code; OpenAI Codex is exempt.
