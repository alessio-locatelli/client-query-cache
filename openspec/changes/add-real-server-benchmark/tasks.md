# Tasks

## 1. Dependency and connection setup

- [ ] 1.1 Update `justfile`'s `pytest` and `tests_and_coverage` recipes to add `--env-file .env` to their `uv run`/`uv run -- coverage run` invocation only when `.env` exists at the repo root; verify both recipes still run with no error and no `--env-file` flag when `.env` is absent, and that a value from a temporary `.env` reaches a probe command's environment when it is present.
- [ ] 1.2 Add `.env.example` documenting the new `REAL_MONGODB_URI` variable (a placeholder value, no real credentials), and add a short `CONTRIBUTING.md` section explaining what it is for, that it is loaded automatically via `uv run --env-file` once present, and pointing to a free-tier MongoDB Atlas cluster as one way to obtain a compatible deployment; verify by reading the rendered section for accuracy against the behavior implemented in this change.
- [ ] 1.3 Create `tests/benchmark/real_server/__init__.py` and `tests/benchmark/real_server/conftest.py` with a session-scoped fixture that reads `REAL_MONGODB_URI` from `os.environ`; verify the fixture skips with an explicit reason when `GITHUB_ACTIONS` (or `CI`) is truthy or when the variable is unset/empty, and yields the URI otherwise, via a focused unit test that monkeypatches the environment.

## 2. Workload workers

- [ ] 2.1 Implement top-level, picklable writer and reader worker functions in `tests/benchmark/real_server/workers.py`: the writer repeatedly inserts/updates a small, fixed set of `faker`-generated documents at a rate constant; the reader repeatedly reads that same document-ID set, either through `CacheManager` or directly through `pymongo`, selected by a parameter. Verify with a unit test (against the existing `testcontainers`-backed `mongodb_uri` fixture, not the real deployment) that each worker function runs standalone and performs the expected operation shape.
- [ ] 2.2 Add command-count and wall-clock instrumentation to the reader worker: register a `pymongo.monitoring.CommandListener` counting `CommandStartedEvent`s, and time only the steady-state loop after a discarded warmup pass that populates the cache and lets the change stream start receiving events. Verify with the same local, container-backed unit test that the warmup reads are excluded from both the returned timing and the returned command count.

## 3. Real-server benchmark test

- [ ] 3.1 Add `tests/benchmark/real_server/test_cache_benefit.py`, marked `@pytest.mark.benchmark`, that spawns the writer process, then runs the cached reader phase and the uncached reader phase (each as its own process) against the real deployment from the `REAL_MONGODB_URI` fixture, and collects each phase's wall-clock duration and command count. Verify by running it locally against a real configured free-tier deployment.
- [ ] 3.2 From that first real run, record the measured cached duration, uncached duration, and command counts; hard-code them as named module-level constants (per `test-value-conventions`) with the cache-benefit ratio assertion (cached ≥ 2x faster, tight), the wall-clock ceilings (first measurement × a documented safety margin), and the command-count ceilings (first measurement, exact). Verify the test passes against the same deployment immediately after recording the constants.
- [ ] 3.3 Verify the two skip paths end-to-end: running the documented local benchmark command with `GITHUB_ACTIONS=true` set skips without a network attempt, and running it with `REAL_MONGODB_URI` unset skips with a distinct, explicit reason.
- [ ] 3.4 Confirm `just tests_and_coverage` collects and runs the new test locally when `REAL_MONGODB_URI` is configured, and that the documented CI workflows (`test.yml`) continue to pass without the variable configured, since CI already lacks the gitignored `.env` file.

## 4. Code Quality

- [ ] 4.1 Scan every test added or edited in this change (`tests/benchmark/real_server/*`) and confirm the `AGENTS.md` "Writing Tests" guidelines are applied, including `@pytest.mark.parametrize` for the cached/uncached worker-selection unit test in 2.1 and fixture-based setup/teardown instead of inline `try`/`finally`.
- [ ] 4.2 Confirm no prose/comments were added beyond a short inline note recording the origin of a hard-coded threshold constant; every other "why" explanation lives in this change's specs/design or the commit body.
