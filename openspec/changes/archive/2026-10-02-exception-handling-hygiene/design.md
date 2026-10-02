# Design

## Context

See proposal.md for motivation. The project requires Python 3.14 (`requires-python = ">=3.14.6"`), so `src/` already uses the parenthesis-free form `except A, B:` (PEP 758). Both spellings must be found. Coverage runs through `covdefaults` (branch coverage, 100% required), so an `except A, B:` clause is fully covered as soon as either `A` or `B` is raised.

The 22 sites, found with the two commands from the request (the single-line `git grep` finds both spellings; the multi-line `rg` finds the two bracketed tuples that wrap across lines at `topology.py:235` and `await_run.py:559`):

| Area                                                             | Sites | Types                                                                                                                                                  |
| ---------------------------------------------------------------- | ----- | ------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `src/_core/find_one_reads.py:61`                                 | 1     | `TypeError, ValueError` around `Collation(**document)`                                                                                                 |
| `src/_core/manager.py:478,601,679`, `src/_core/projection.py:32` | 4     | `BSONError, OverflowError` around `encode_value` / `bson.encode`                                                                                       |
| `src/{asynchronous,synchronous}/streams.py`                      | 4     | `StopAsyncIteration`/`StopIteration, PyMongoError` around `next()`; `BSONError, TypeError, ValueError` around `bson.encode`                            |
| `benchmarks/stream_cost/`                                        | 10    | config parsing, JSON validation, Docker lifecycle, CPU stats, setup/Mongo/timeout failures                                                             |
| `tests/`                                                         | 3     | `TypeError, ValueError, OperationFailure` (async and sync collection tests), `OSError, RuntimeError, ValueError, DNSException` in `atlas_bandwidth.py` |

`contextlib.suppress` usage (found with `git grep -nE 'suppress\(|import suppress' -- '*.py'`):

| File                                               | Uses | Suppressed types                                                                    |
| -------------------------------------------------- | ---- | ----------------------------------------------------------------------------------- |
| `src/{asynchronous,synchronous}/streams.py`        | 8    | `PyMongoError` (stream close), `asyncio.CancelledError` (awaiting a cancelled task) |
| `benchmarks/stream_cost/proxy.py`                  | 3    | `OSError` (socket teardown)                                                         |
| `benchmarks/stream_cost/topology.py`               | 2    | `DockerException, ContainerStartException` (container stop)                         |
| `tests/{asynchronous,synchronous}/test_streams.py` | 2    | `asyncio.CancelledError`, `StreamLifecycleError`                                    |

Ruff runs with `select = ["ALL"]`, so `suppressible-exception` (SIM105) currently asks for `try`/`except`/`pass` to be rewritten into `suppress`.

## Goals / Non-Goals

**Goals:**

- After the change, no tracked Python `except` clause lists a type that the guarded code cannot raise.
- Every surviving type is observable on its own in branch coverage.
- A repeatable rule in `AGENTS.md` keeps new multi-type clauses from reappearing unexamined.

**Non-Goals:**

- Changing which failures are handled, their messages, or the exception types users see.
- Auditing `pytest.raises((A, B))` tuples; they do not handle production failures and can follow as their own change if wanted.
- Widening or narrowing a handler to "fix" semantics. A type that can be raised but is currently untested is tested, not removed.

## Decisions

### Decide per type, from evidence, not from the type's plausibility

For each listed type, determine whether the guarded statement can raise it by reading the callee's source (PyMongo, `bson`, `json`, `docker`/`testcontainers`, `dns`) or by running a minimal reproduction under `/tmp/agents/`. The question is "which input makes this line raise `X`?". If no input does, delete `X`. Plausible-sounding types (`OverflowError` next to `BSONError`, `ValueError` next to `TypeError`) are the specific suspects this change exists to test.

Alternative: delete types on a coverage run alone. Rejected: coverage cannot distinguish "unreachable" from "reachable but untested", which is exactly the hole being closed here.

### Split into one clause per type when handlers differ or are tiny; use `isinstance` dispatch when they share a long body

- Handlers that return a constant or re-raise (`return False`, `return`, `return DECLINED_UNENCODABLE`) become separate `except` clauses. The duplicated body is one line, and each clause is its own coverage line.
- Handlers that already branch on the type, or that share a multi-line body (`await_run.py:450,559`, `guard_report.py:73`), keep one clause and use `isinstance` dispatch where one exists. `await_run.py` already does so; each branch of the dispatch then needs a test that takes it.
- Handlers with a shared multi-line body and no existing dispatch get a single clause plus `isinstance` only when the types are all reachable and the body differs in at most one expression. Otherwise they are split and the shared body is extracted into a small helper to respect DRY.

Alternative: always split. Rejected: it duplicates multi-line bodies (for example `topology.py:116`) and violates DRY. Alternative: always `isinstance`. Rejected: it adds a branch per type to hot-path modules for no benefit on one-line handlers.

### `asynchronous/` and `synchronous/` modules change in lockstep

`streams.py` exists in both packages with the same clauses. Whatever is decided for one is applied to the other in the same commit, with the matching test change in `tests/asynchronous/` and `tests/synchronous/`.

### Tests that catch tuples are fixed with parametrization, not deleted

`test_collection.py:1947` and `:1896` catch `(TypeError, ValueError, OperationFailure)` to compare PyMongo's failure with the cache's failure via `type(error)`. This is a differential check whose set of types depends on the input in `options`. It is kept; the audit only confirms that each listed type is produced by at least one parametrized case, and removes the ones that never are. `atlas_bandwidth.py:202` is audited the same way.

### Ban `contextlib.suppress` and enforce it with Ruff

Evidence (reproduced with `coverage run --branch` on a script under `/tmp/agents/suppress/`, exception never raised in either case):

| Construct                                     | Coverage result                         |
| --------------------------------------------- | --------------------------------------- |
| `with contextlib.suppress(ValueError): x = 1` | 100%, no missed line or partial branch  |
| `try: x = 1` / `except ValueError: x = 2`     | the `except` body is reported as missed |

`suppress` has no body that coverage can mark as unexecuted, so a redundant `suppress` is undetectable and permanent. The ban is project-wide (`src/`, `benchmarks/`, `tests/`, `scripts/`).

Replacement: `try: ... except ExampleError: pass`. When a test raises the exception, the `pass` line is covered; when none can, coverage flags it and the whole `try` is deleted. Do not add `# pragma: no cover` to keep an unreachable handler.

Enforcement in `ruff.toml`:

- `[lint.flake8-tidy-imports.banned-api] "contextlib.suppress"` with a message pointing at this rule. Verified with Ruff 0.16.10: it flags `contextlib.suppress(...)` calls and `from contextlib import suppress`.
- Add `suppressible-exception` to `ignore`; with `select = ["ALL"]` SIM105 would otherwise demand the banned construct.

Alternative: ban by convention in `AGENTS.md` only. Rejected: contributors and agents reintroduce it unnoticed. Alternative: keep `suppress` and require a test per suppressed type. Rejected: no tool can check that requirement, which is the defect.

### Record the rules in `AGENTS.md`

Add two development guidelines beside the existing "avoid `dict.get()`" guideline: an `except` clause names one exception type, or several only when each is demonstrably reachable and covered; `contextlib.suppress` is banned in favour of `try`/`except`. No OpenSpec spec changes because the rules govern how contributors write code, not product behavior.

## Risks / Trade-offs

- [A type is removed that real-world input can raise but no test or reading of the callee reveals] → Prefer the callee's documented exceptions; when documentation is silent and the source is ambiguous, keep the type and add a test that raises it. Never remove on absence of evidence alone.
- [Platform- or version-dependent exceptions (Docker, DNS, `OSError`) cannot be reproduced locally] → Keep them, give each its own clause, and cover them with a fake that raises the type; do not add `# pragma: no cover` for a type that real runs can hit.
- [Upstream defects or undocumented exceptions discovered during the audit] → Document them under `docs/` with a tracking ticket URL, per `AGENTS.md`; ask the user to file one if none exists.
- [Duplicated one-line handler bodies after splitting] → Accepted; extracted helpers only when the body is more than a few lines.
- [Hot-path regression in `manager.py`/`projection.py`] → Exception clauses add no cost on the non-raising path; confirm with the existing benchmark suite only if the final code differs structurally from a clause split.
