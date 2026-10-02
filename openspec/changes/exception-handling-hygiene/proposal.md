# Proposal

## Why

Several `except` clauses list two or more exception types, and at least some of those types can never be raised by the guarded code. Because the clause is covered as soon as any one listed type fires, coverage cannot show that the remaining types are dead, so speculative handling accumulates unnoticed. Splitting these clauses makes each exception type independently visible to line and branch coverage, so dead handling is exposed and deleted.

`with contextlib.suppress(ExampleError):` hides the same defect even more completely. A reproduction (see `design.md`) shows that coverage reports 100% for a `suppress` block whose exception is never raised, while the equivalent `try`/`except ExampleError: pass` reports the `except` and `pass` lines as missed. `suppress` is therefore another way to mask redundant pseudo-defensive code and is banned.

## What Changes

- Audit every `except` clause that names two or more exception types (22 tracked sites across `src/`, `benchmarks/` and `tests/`; the exact inventory and discovery commands are in `design.md`).
- For each listed exception type, establish whether the guarded code can raise it, using the library source or a minimal reproduction.
- Delete the types that cannot be raised.
- Where two or more types remain, express each one so that coverage observes it separately: one `except` clause per type, or a single clause followed by an `isinstance` dispatch when the handlers share most of their body.
- Replace every `contextlib.suppress(...)` (15 uses in 5 files) with `try`/`except ... : pass`, or delete the handling when the exception is never raised.
- Ban `contextlib.suppress` project-wide through Ruff (`banned-api`), and disable Ruff's `suppressible-exception` (SIM105) rule, which would otherwise ask for it back.
- Record both rules in `AGENTS.md` so that multi-type `except` clauses and `suppress` are not reintroduced.
- No public behavior, error message, or exception type surfaced to users changes.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. This is a behavior-preserving refactor; the change sets `skip_specs: true`.

## Impact

- Code: `src/client_query_cache/_core/{find_one_reads,manager,projection}.py`, `src/client_query_cache/{asynchronous,synchronous}/streams.py`, `benchmarks/stream_cost/*.py` (including `proxy.py`), `tests/{asynchronous,synchronous}/test_{collection,streams}.py`, `tests/benchmark/real_server/atlas_bandwidth.py`.
- Tooling: `ruff.toml` (banned API, ignored rule).
- Tests: new regression tests only where a surviving exception type lacks a test that raises it; types that cannot be raised are removed instead of tested. Coverage stays at 100% without new pragmas.
- Docs: `AGENTS.md` gains two development guidelines. No `README.md` or `docs/` change, as no public interface changes.
- Performance: none expected; exception clauses cost nothing on the non-raising path. No benchmark is required beyond confirming the hot-path modules (`manager.py`, `projection.py`) keep the same non-raising bytecode path.
