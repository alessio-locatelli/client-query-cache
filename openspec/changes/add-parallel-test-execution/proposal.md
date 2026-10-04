# Proposal

## Why

The full test suite runs serially despite independent test files and disposable database fixtures. Parallel execution can reduce its elapsed time, provided worker counts, fixture ownership, logging, and coverage remain controlled.

## What Changes

- First trial serial, two-worker, and four-worker execution from the CLI to establish speedup and expose conflicts before changing repository defaults.
- If the trial supports parallel execution, add development dependencies on `pytest-xdist` and `pytest-cov`, with committed lockfile updates.
- Default ordinary pytest runs to bounded automatic parallelism with file-based scheduling; explicit numeric worker counts and serial mode remain contributor choices.
- Preserve worker-local disposable MongoDB ownership and module fixture reuse without introducing a shared database or custom scheduler.
- Give workers separate log files and include their diagnostics in the existing CI failure artifact.
- Measure and combine coverage from all workers in the existing single full-suite invocation, preserving branch coverage policy and strict exclusion checks.
- Keep dedicated memory profiling and benchmark commands serial. Preserve the full suite's existing test selection, including its optional real-server benchmark; document that full-suite timings are not isolated benchmark evidence.
- Confirm the speedup with the final full-suite coverage command, recording elapsed time and resource costs in a concise reproducible report.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `test-environment`: Bounded parallel defaults, file scheduling, worker-owned fixtures and logs, combined worker coverage, serial diagnostic and measurement paths.
- `continuous-integration`: Retention of controller and worker logs when the parallel coverage job fails.

## Impact

After a successful trial, implementation will affect `pyproject.toml`, `uv.lock`, `pytest.ini`, `tests/conftest.py`, `justfile`, `tox.ini`, `.github/workflows/test.yml`, and contributor documentation. Representative commands will verify worker isolation and logs; no permanent tests of test-tree helpers are planned. Worker processes duplicate collection and session fixtures, so the default requires measured CPU, memory, and container-cost evidence.
