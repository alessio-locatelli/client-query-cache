## 1. Migrate project management to uv

- [ ] 1.1 Replace Poetry-specific metadata and the Poetry build backend with PEP 621 dependency groups and `uv_build>=0.12.9,<0.13`; retain `requires-python = ">=3.13"` and verify `uv build` creates both a wheel and source distribution.
- [ ] 1.2 Resolve and commit `uv.lock`, remove `poetry.lock` with version-control-aware deletion, and verify `uv sync --all-groups --locked` completes without modifying project metadata or the lockfile.
- [ ] 1.3 Define explicit `uv` groups for test/coverage, integration/e2e, quality tooling, and benchmarks without adding those tools to published runtime dependencies; verify a clean isolated wheel install depends only on declared runtime dependencies.
- [ ] 1.4 Align mypy, Ruff, pytest, package metadata, and any Python-version declarations to the 3.13+ policy; verify each configured parser accepts its configuration and reports the intended version.

## 2. Establish reproducible quality gates

- [ ] 2.1 Add a pinned `.pre-commit-config.yaml` for Prek with repository hygiene hooks, Ruff lint/format, the pinned Ruff-extra rule hook, detect-secrets, Vulture, mypy, slotscheck, and a pinned Prettier check; verify `prek run --all-files` discovers every hook.
- [ ] 2.2 Configure the Ruff-extra hook to use an isolated Python 3.14 interpreter while package analysis and tests retain the Python 3.13 baseline; verify the hook runs successfully from a Python 3.13 project environment and `pyproject.toml` still declares 3.13+.
- [ ] 2.3 Add reviewed configuration for each quality tool, including a minimal detect-secrets baseline and documented narrow exclusions; seed a temporary detected violation for each practical gate and verify it exits nonzero before removing the fixture.
- [ ] 2.4 Run the complete quality gate against the proof-of-concept files, fix every reported source, test, configuration, and documentation violation, and verify `prek run --all-files` succeeds with no broad suppression added.

## 3. Build the layered test environment

- [ ] 3.1 Register strict pytest markers and documented `uv` commands for unit, integration, end-to-end, and benchmark suites; reclassify existing tests so the default unit command never opens a MongoDB connection, and verify that command works with no container runtime available.
- [ ] 3.2 Add a Testcontainers-Python fixture that starts a disposable MongoDB single-node replica set, initializes it, waits for primary election, exposes dynamically assigned direct connection settings, and closes all clients and containers; verify an integration test performs a raw read and write through the fixture.
- [ ] 3.3 Replace the existing `localhost:27017` and Compose-state test dependency with per-test database/collection isolation and separate cached and raw PyMongo writer clients; verify parallelizable integration tests do not use the fixed Compose port or an external database.
- [ ] 3.4 Add end-to-end test support that builds the wheel, installs it into a clean temporary `uv` environment, invokes only its public API, and uses an independent raw writer for a cache-coherency scenario; verify the end-to-end marker passes against the disposable replica set.
- [ ] 3.5 Add a container-runtime preflight and CONTRIBUTING guidance for Docker Engine, the Docker API-compatible Podman alternative, and unavailable-runtime behavior; verify the diagnostic identifies the missing prerequisite without attempting to contact any user database.

## 4. Enforce coverage and configure benchmarks

- [ ] 4.1 Configure branch coverage for every importable `mongo_client_cache` production module, combine the relevant test-tier data, and set the required threshold to 100 percent; verify an intentionally uncovered reachable branch makes the command fail.
- [ ] 4.2 Add or revise deterministic tests until the production package has 100 percent statement and branch coverage, removing dead code rather than excluding ordinary behavior; verify `coverage report` and its XML output both show 100 percent.
- [ ] 4.3 Add pytest-benchmark configuration, an explicit benchmark marker/command, and versioned result-artifact paths that record revision, interpreter, dependency environment, and parameters; verify ordinary test and coverage commands skip benchmark sampling and the benchmark command writes metadata.
- [ ] 4.4 Keep detailed change-stream cost fixtures, byte accounting, and controlled-resource workload scenarios in `measure-change-stream-costs`; verify the generic benchmark configuration can run those tests without introducing a hosted-runner timing threshold.

## 5. Document contributor and CI workflows

- [ ] 5.1 Add CONTRIBUTING guidance for `uv` installation/use, lock updates, quality checks, test-tier commands, Docker and Podman prerequisites, failure diagnostics, coverage, and benchmark artifacts; verify all commands against the implemented configuration and link to the Testcontainers and uv primary documentation.
- [ ] 5.2 Correct the README's unsupported claims of complete coverage, benchmarking, and stress testing, then link readers to contributor guidance rather than duplicating mutable developer commands; verify README statements match the produced test and benchmark evidence.
- [ ] 5.3 Add GitHub Actions quality/build, unit/coverage, and Docker-backed integration/end-to-end workflows that install dependencies with `uv sync --locked`; verify workflow YAML, lockfile enforcement, wheel installation/import, Python 3.13 and 3.14 job coverage, and safe artifact paths.
- [ ] 5.4 Add an explicitly dispatched benchmark workflow that uploads result artifacts without a host-dependent performance pass/fail condition; verify the workflow does not run as part of the default pull-request checks.
- [ ] 5.5 Run the full applicable quality, build, unit, coverage, integration, end-to-end, and benchmark validation; record unavailable local-runtime evidence if applicable, run `openspec validate scaffold-quality-engineering --strict`, and review the final diff before marking this change complete.
