# Tasks

## 1. Behavioral minimum-driver environment

- [x] 1.1 Update `[testenv:pymongo-min]` in `tox.ini` according to the resolver, version-preflight, and test-selection decisions in `design.md`. Verify the effective configuration with `uv run -- tox config -e pymongo-min`; ensure test tooling comes from the existing group and no concrete PyMongo version is repeated.
- [x] 1.2 Add `just test-pymongo-min` following the host-runtime decision in `design.md`, including tox environment forwarding of the required container variables. Add its reproduction command and scope to `CONTRIBUTING.md`'s testing instructions. Run the command with the repository-pinned toolchain against disposable MongoDB; record the exact interpreter, installed driver, selected tests, elapsed time, and outcome in the implementation commit body. In a disposable tox environment, verify the preflight rejects an installed driver newer than the declared floor. Confirm `pyproject.toml` and `uv.lock` remain unchanged.

## 2. Required PR coverage

- [x] 2.1 Implement the job and aggregate-gate decision in `design.md` in `.github/workflows/test.yml`. Confirm a minimum-job failure, cancellation, or unexpected skip fails the stable gate while normal locked-driver lanes retain their existing behavior; use the existing gate's explicit result checks and the repository's workflow tooling. Reuse task 1.2's execution evidence when the job invokes the same tested command; rerun only if wiring changes its execution inputs. Keep diagnostic artifacts distinguishable from existing matrix artifacts.
- [x] 2.2 Add `tox.ini` to the Python inputs in `scripts/ci_scope.py` and add a case to the existing parametrized test in `tests/test_ci_scope.py`. Verify `just pytest -- tests/test_ci_scope.py` passes with the new case and existing unrelated-documentation cases; confirm the workflow consumes that scope for the minimum job.

## 3. Code Quality

- [x] 3.1 Review every test file edited or added during implementation, including its pre-existing tests, against `AGENTS.md`'s Writing Tests guidelines. Verify shared case logic stays parametrized and fixture setup remains outside tests.
- [x] 3.2 Claude-only restriction on new code prose is inapplicable: planning authored by OpenAI Codex.
- [x] 3.3 Align the shared PR-workflow uv rationale with the setup-toolchain action's version pin.
