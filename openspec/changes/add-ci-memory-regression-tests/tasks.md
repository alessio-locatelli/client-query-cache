# Tasks

## 1. Memory tier and workload

- [ ] 1.1 Add a Linux/macOS-qualified `memory` dependency group with a compatible stable pytest-memray release and update `uv.lock`. Verify locked synchronization on the repository interpreter and that pytest exposes `--memray` and `--trace-python-allocators`; do not add a runtime dependency.
- [ ] 1.2 Register `memory` and `limit_memory` markers in `pytest.ini`, exclude memory by default, and audit explicit marker selections in `justfile` and `tox.ini`. Add `just test-memory` and an opt-in tox memory environment using the flags in design decision 3. Verify collection selects exactly the two memory cases for the dedicated command and none for the provided ordinary tiers; ordinary runs must not enable profiling. Ignore `memory-reports/` in Git.
- [ ] 1.3 Add `tests/memory/conftest.py` fixtures for profiler activation checks, seeded synthetic payloads, and guaranteed core closure. Explicit memory selection without active profiling must fail visibly; missing plugin dependencies and empty selection must yield nonzero command exit codes. Keep the dedicated Just command independent of the container bridge and document unsupported-platform errors with an official Memray link.
- [ ] 1.4 Implement `tests/memory/test_cache_churn.py` as one parametrized test for identity-with-alias and namespace admissions. Follow design decision 1: 4 MiB shared budget, 128 KiB entry maximum, two namespaces, eight cycles of 1,024 fresh 64 KiB payload admissions, immediate hits, and writes/misses/readmissions every sixteenth admission. Use short-lived helpers with no growing workload history. Verify actual admissions, hits, and eviction occur in both cases.
- [ ] 1.5 Add quiescent checks every 128 admissions for budget and resident metadata consistency, and cycle-end checks for zero usage and empty namespace entry indexes, identities, and aliases after clear. Close the core and check zero usage before returning. Verify both cases complete these assertions and that no assertion assumes ordinary writes physically reclaim all entries immediately.
- [ ] 1.6 Add a brief `CONTRIBUTING.md` command/link and create `docs/development/memory-regression-tests.md` describing the tier, workload, profiling boundary, limitations, and calibration procedure. Verify the documented command profiles only the new tier without MongoDB and use the official pytest-memray reference for profiler semantics.

## 2. Calibration and sensitivity

- [ ] 2.1 Measure ten fresh-process profiled runs per case on Ubuntu 24.04 with the repository interpreter and locked dependencies, using exactly the dedicated command's capture/tracing flags and no coverage. Use temporary diagnostic ceilings during calibration only. Record peak ranges, maximum H, profiled durations, and trace sizes in the development document; keep raw output untracked. Confirm the documented environment matches CI.
- [ ] 2.2 Replace temporary ceilings with case-specific literal `limit_memory` markers calculated as `ceil(1.5 * H / 1048576) MiB`, at most 32 MiB. Verify every baseline peak is below its committed ceiling. If that rule cannot produce a ceiling within 32 MiB, investigate and report the blocker rather than loosening it automatically.
- [ ] 2.3 Perform the temporary retention experiment from design decision 2 for each case: retain admitted encoded values outside normal cache accounting while leaving structural assertions intact. Verify a Memray ceiling failure occurs, record the failure and peak in the calibration document, and remove the injected fault. Do not commit the fault or a test of this experiment.
- [ ] 2.4 Measure the same workload without profiling for comparison using a temporary local harness that bypasses only the activation check and does not alter the workload. Inspect healthy Memray allocation stacks, record the observed allocation bottleneck and profiling overhead in the development document, and include the concise measurements in the implementation commit body. Keep the comparison harness untracked.

## 3. Pull request gate

- [ ] 3.1 Add a dedicated Ubuntu 24.04 memory job to `.github/workflows/test.yml` using `needs: [scope, prek, prettier]`, `scope.outputs.python`, existing action pins and read-only permissions, locked synchronization, `just test-memory`, and a ten-minute timeout. Verify the workflow selects it for the existing Python scope, skips unrelated documentation-only changes, and waits for quality gates; reuse `scripts/ci_scope.py` unchanged unless an actual uncovered input is found.
- [ ] 3.2 Upload `memory-reports/` on memory-job failure with seven-day retention. Verify an over-ceiling run exposes allocation diagnostics and a startup failure remains visible when no trace exists. Document CI execution and diagnostic locations in the development guide without committing binary traces or raw calibration output.

## 4. Code Quality

- [ ] 4.1 Scan the entire file for edited or added tests, including pre-existing tests within each file, and ensure the Writing Tests guidelines from `AGENTS.md` are applied, including parametrization. Verify the two admission modes share test logic and cleanup resides in fixtures.
- [x] 4.2 If you are Claude Code, confirm that no new prose was added to code; all why explanations belong in specs and commit bodies. Inapplicable: proposal authored by OpenAI Codex, which is exempt.
