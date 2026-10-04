# Tasks

## 1. CLI trial before repository changes

- [x] 1.1 Trial xdist without editing dependency metadata or repository defaults using the command below from the repository root. Replace `-n 2` with `-n 0` or `-n 4` for the other modes, keeping every other argument unchanged. Have the configured image available and run each mode three times in alternating order. Keep raw output untracked; record elapsed medians/ranges, test/skip counts, slowest tests, and observed memory/container costs.

```bash
bash <<'BASH'
set -euo pipefail
source scripts/testcontainers-bridge.sh
trial_env_args=()
if [[ -f .env ]]; then
    trial_env_args=(--env-file .env)
fi
CI=true uv run "${trial_env_args[@]}" --locked \
    --with 'pytest-xdist[psutil]>=3.8.0' -- pytest \
    --log-file=/dev/null --durations=10 -n 2 --dist=loadfile \
    tests/core tests/synchronous tests/asynchronous \
    tests/benchmark/stream_cost/test_await_run_integration.py \
    tests/benchmark/stream_cost/test_compression_matrix_runner_integration.py
BASH
```

- [x] 1.2 Assess the trial before proceeding: select an automatic limit of two or four only if a parallel mode consistently improves elapsed time with matching test outcomes and no resource or isolation failures. Inspect distinct dynamically allocated worker containers and cleanup through runtime observations. If the trial is blocked or does not demonstrate a useful speedup, stop before tasks 2–4 and record the result in this change's design. Fix only observed defects necessary for parallel execution; do not add fixture-coordination harnesses or refactor unrelated tests.

## 2. Dependencies, scheduling, and diagnostics

- [x] 2.1 After a successful trial, add `pytest-xdist[psutil]>=3.8.0` and `pytest-cov>=7.1.0` to the development group, regenerate `uv.lock`, and verify `uv sync --locked` installs both plugins.
- [x] 2.2 Add `-n auto --dist=loadfile` to `pytest.ini` while retaining submodule exclusion and marker selection. In `tests/conftest.py`, wrap `pytest_xdist_auto_num_workers` to limit xdist's detected count to the value selected in task 1.2; preserve numeric requests and xdist's default restart behavior. With an existing unit-test file, observe bounded automatic/logical counts, exactly two workers for `-n 2`, five for `-n 5`, and serial execution for `-n 0`. Do not add permanent tests of this hook or upstream option parsing.
- [x] 2.3 Route worker file logs in `tests/conftest.py` before pytest logging opens them: keep `pytest.log` for the controller, use paths such as `pytest-gw0.log` for workers, preserve custom parent directories, and leave serial destinations and `/dev/null` unchanged. Verify by running existing tests with two workers and inspecting separate output files, then repeat with a custom destination and serial `/dev/null`; do not commit meta-tests of logging helpers.
- [x] 2.4 Extend the existing failure-artifact path in `.github/workflows/test.yml` to include `pytest.log` and `pytest-gw*.log`, retaining seven-day retention and missing-file behavior. Confirm the files produced by task 2.3 match the artifact paths. Document defaults, explicit numeric overrides, `loadfile` rationale, and log locations in `docs/development/parallel-test-execution.md`, linked from `CONTRIBUTING.md`.

## 3. Coverage and serial measurement commands

- [x] 3.1 Replace `coverage run -m pytest` in `just tests_and_coverage` with `pytest --cov --cov-config=.coveragerc --cov-report=`, retaining the isolated `COVERAGE_FILE`, environment loading, single full-suite invocation, report, and exclusion checks. Compare serial and two-worker production-file/branch measurements with identical inputs; verify worker execution contributes coverage and existing thresholds/exclusion enforcement remain effective. Document the parallel coverage command without adding subprocess instrumentation or changing exclusions.
- [x] 3.2 Add `-n 0` to `just test-memory` and `[testenv:benchmark]`. Document serial debugging (`just pytest -- -n 0 --pdb <node-id>`), live output (`just pytest -- -n 0 -s <node-id>`), and the standalone real-server benchmark command. Verify dedicated measurement tiers start no distributed workers; use `CI=true` for the benchmark tier's existing external-service skip.

## 4. Final full-suite comparison

- [x] 4.1 Compare three serial and three selected-default full-suite coverage runs on the same host in alternating order. Use `CI=true PYTEST_ADDOPTS='-n 0' just tests_and_coverage` for serial and `CI=true just tests_and_coverage` for the default. Include fixture startup and normal logging in elapsed time; compare test/skip counts, production coverage, slowest tests, process-tree memory, and container costs. Confirm memory/submodule exclusions and conditional skips remain unchanged. Do not accept a default that loses the trial's speedup or changes outcomes.
- [ ] 4.2 Add a concise initial-trial and final-comparison summary, host/tool versions, resource observations, and exact reproduction commands to `docs/development/parallel-test-execution.md`. Keep raw output untracked and include timings, slow-test profiling, and resource measurements in the implementation commit body. If final measurements require a lower automatic limit, update the hook and documentation and repeat the comparison before completion.

- [x] 4.3 Fix the observed wall-clock dependency in seeded benchmark document timestamps. Verify determinism across seeds while the reference clock advances, retain BSON round-trip and document-size assertions, and restart the final serial/default comparisons with the corrected generator.
