# Proposal

## Why

The cache's BSON budget and small eviction tests do not measure allocations retained outside budget accounting. A focused CI memory check should catch entries, identity state, aliases, or reclamation-index tokens accumulating as a bounded cache processes many documents.

## What Changes

- Add an opt-in memory test tier using pytest-memray, with a dedicated local command and a Linux pull request job.
- Exercise the shared cache core with fixed namespaces, a small budget, and repeated admissions, hits, eviction, and namespace clears. Cover identity admissions with aliases and namespace-guarded admissions as separate parametrized cases.
- Fail on incorrect budget/reclamation behavior or on a calibrated, committed peak-allocation ceiling. Verify that a deliberate retained-entry regression fails the guard.
- Keep profiling out of ordinary unit, integration, end-to-end, coverage, and latency benchmark runs.
- Document the workload, measurement boundary, threshold calibration, and reproduction command in contributor documentation.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `test-environment`: Define an isolated memory tier with meaningful allocation and reclamation assertions.
- `continuous-integration`: Run the dedicated memory gate for Python-validation changes after quality checks and preserve safe failure diagnostics.

## Impact

Implementation will affect development dependencies and `uv.lock`, `pytest.ini`, `tests/memory/`, test commands in `justfile` and `tox.ini`, `.github/workflows/test.yml`, `CONTRIBUTING.md`, and a new `docs/development/memory-regression-tests.md`. No public API or cache-budget semantics change is proposed. The shared core serves synchronous and asynchronous managers, but this gate does not establish cursor, thread, or asyncio-task cleanup. Telemetry retention and long-running process RSS are outside this change.
