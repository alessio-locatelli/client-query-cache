# Tasks

## 1. Guard selection

- [x] 1.1 Add a pattern matching every path under `native/` to `_RELEVANT_PATTERNS` in `benchmarks/stream_cost/guard_scope.py`. Add `test_changed_files_require_guard` cases in `tests/benchmark/stream_cost/test_guard_scope.py` for a native source module, `native/shared-index/Cargo.toml`, and `native/shared-index/Cargo.lock`, each selecting the guard; verify with `just pytest tests/benchmark/stream_cost/test_guard_scope.py`.
- [x] 1.2 Name native code in the guard job's skip summary message in `.github/workflows/test.yml` and in the skip sentence of `docs/development/performance-regression-guard.md`; verify with `rg -n 'native' .github/workflows/test.yml docs/development/performance-regression-guard.md`.

## 2. Code Quality

- [x] 2.1 Scan `tests/benchmark/stream_cost/test_guard_scope.py` in full and confirm the "Writing tests" guidelines from `AGENTS.md` are applied, including parametrization.
- [x] 2.2 Confirm no new prose was added to code.
