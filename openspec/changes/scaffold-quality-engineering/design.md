## Context

See [proposal.md](proposal.md) for the motivation. The checked-in project is a proof of concept: it declares `requires-python = ">=3.13"`, uses Poetry for its build backend and test group, has a Python 3.12 mypy configuration, and has no hook, coverage, benchmark, or CI configuration. `docker-compose.yaml` can start a replica set on a fixed host port, but it is not isolated test infrastructure.

The existing foundation plan requires real replica-set tests for change streams, and the stream-cost plan requires opt-in benchmark execution. This change establishes shared tooling without redefining either plan's cache semantics or detailed workload protocol.

## Goals / Non-Goals

**Goals:**

- Give a fresh contributor one `uv`-based, locked setup for development, testing, linting, building, and CI.
- Make unit, integration, and end-to-end tests distinct in cost and prerequisites while retaining a complete production branch-coverage gate.
- Make a single-node replica set disposable and test-owned so change-stream testing is reproducible locally and in GitHub Actions.
- Apply the requested Ruff-extra, Prek, Vulture, mypy, Prettier, and related checks without silently weakening the Python 3.13+ support policy.
- Provide a generic, opt-in benchmark substrate compatible with the detailed stream-cost benchmark change.

**Non-Goals:**

- This change does not implement cache behavior, change-stream metrics, a performance threshold, or a production MongoDB deployment.
- This change does not promise that all container runtimes behave identically. Docker Engine is the CI baseline; Podman is a documented local alternative.
- This change does not make Compose the test harness or require a developer to keep a MongoDB service running.
- This change does not publish packages, upload to a registry, or add a release credential.

## Decisions

### Use `uv` for resolution, environments, and builds

Replace Poetry sections and `poetry.lock` with PEP 621 metadata, standardized `[dependency-groups]`, and a committed `uv.lock`. Use `uv_build>=0.12.9,<0.13` as the PEP 517 backend because the current distribution is pure Python and has a conventional package layout. `uv` documents `uv_build` as its native pure-Python backend and documents committing its universal `uv.lock` for reproducible installs. [uv build backend](https://docs.astral.sh/uv/configuration/build-backend/), [uv lockfile](https://docs.astral.sh/uv/concepts/projects/layout/)

Separate groups will keep the published PyMongo dependency independent of development tools: a default development group for test/coverage, focused groups for lint/type/hook support, integration/e2e, and benchmarks as needed. `uv sync --all-groups --locked` will be the deterministic developer and CI setup; targeted `uv run --group ...` commands will avoid installing optional heavy tooling for a fast task.

Alternatives considered:

- Keep Poetry and invoke `uv` only as a faster installer. This leaves two dependency authorities and violates the requested developer workflow.
- Retain `poetry-core` as the build backend. It is technically possible but retains Poetry in the package's build path without a present need for its features.
- Use a bespoke requirements-file collection. It would duplicate project metadata and dependency resolution.

### Make Prek the unified quality entry point

Add a pinned `.pre-commit-config.yaml` for Prek. It will include the hygiene checks used by the referenced Ruff-extra project; Ruff formatting/linting; the pinned Ruff-extra hook; detect-secrets with a reviewed baseline; Vulture; mypy; slotscheck; and a pinned Prettier check for supported text formats. Tool configuration will live in project configuration files, with `ruff` and `mypy` set to the actual Python 3.13 baseline.

The referenced Ruff-extra hook requires Python 3.14. Prek will create an isolated hook environment using Python 3.14, while `uv` test/type/build jobs continue to validate the package on Python 3.13 and later. This is a tooling interpreter, not a runtime dependency, and preserves `requires-python = ">=3.13"`.

Alternatives considered:

- Remove Ruff-extra on Python 3.13. This drops a requested gate precisely where a dedicated hook environment avoids the compatibility problem.
- Raise the package minimum to Python 3.14. That contradicts the established project policy without a runtime feature requiring it.
- Run unrelated linters ad hoc in CI only. That prevents contributors from reproducing the complete check locally.

### Use Testcontainers-Python with a project-owned replica-set fixture

Integration and end-to-end suites will create their own MongoDB container through Testcontainers-Python. A project fixture will start `mongod` with a replica-set name, initialize the one-member set, wait for a writable primary, and expose a dynamically mapped, direct connection string. Tests get separately created cached and raw PyMongo clients. The fixture owns cleanup and must never contact a user-provided database.

Testcontainers requires a Docker API-compatible runtime. Docker Engine is the supported GitHub Actions runtime. Local contributors can use Podman through its Docker-compatible socket if they apply the documented Testcontainers Podman configuration, including its rootless cleanup limitation; the project documentation will give the exact supported commands and a preflight diagnostic. [Testcontainers Python MongoDB guide](https://testcontainers-python.readthedocs.io/en/latest/modules/mongodb.html), [Testcontainers Podman guidance](https://java.testcontainers.org/supported_docker_environment/), [Podman Docker API socket](https://podman-desktop.io/docs/migrating-from-docker/using-the-docker_host-environment-variable)

The static Compose file remains an optional manual debugging aid, not the automated test environment. Fixed ports, pre-existing data, and manually initialized services would make tests non-parallel and prone to false results.

Alternatives considered:

- Use the repository Compose service. It is useful for manual exploration but needs a persistent service, a fixed port, and manual state cleanup.
- Require Docker Compose for all tests. Testcontainers provides test-owned lifecycle and random ports while supporting the same Docker engine.
- Run integration tests against an external shared MongoDB instance. That introduces credentials, state leakage, and topology uncertainty.

### Define test tiers and coverage independently

Pytest markers will make each tier explicit:

| Tier | Default invocation | Environment | Evidence |
| --- | --- | --- | --- |
| Unit | Yes | Python only | Pure cache, canonicalization, lifecycle, and error logic |
| Integration | CI and explicit local command | Testcontainers single-node replica set | Driver, stream, and raw-writer behavior |
| End-to-end | CI and explicit local command | Testcontainers plus built wheel in a clean `uv` environment | Public API packaging and externally originated change behavior |
| Benchmark | Explicit command only | Python or the controlled topology required by the benchmark | Timing and result artifact, not a quality threshold |

Coverage will use branch measurement and combine the tests that execute production code into a single report with `fail_under = 100`. The end-to-end subprocess proves artifact behavior rather than carrying coverage instrumentation; its correctness is required separately. Tests, fixtures, and benchmark helpers are not covered by the production threshold; unused or untested helper code is removed or tested through its observable behavior rather than hidden with a coverage exclusion.

Alternatives considered:

- Require Docker for every unit test. It makes the main feedback loop slower and blocks pure development on a laptop without a container runtime.
- Treat an installed-wheel smoke test as sufficient end-to-end coverage. It cannot prove invalidation from a separate writer or recovery behavior.
- Count benchmarks in default coverage. Benchmark timing and database setup make the normal gate slow and nondeterministic.

### Use CI as verification, not a benchmark oracle

GitHub Actions will have fail-fast quality/build and test jobs. A Python matrix will cover CPython 3.13 and 3.14 for package tests; the dedicated quality job also installs Python 3.14 for the Ruff-extra hook. All jobs will use `uv sync --locked`, and the workflow will fail if syncing would change `uv.lock`. The Docker-capable job runs the database-backed integration and end-to-end tiers. It publishes coverage and failed-test diagnostics without secrets, raw documents, queries, or resume tokens.

Benchmark workflows run only by explicit dispatch or a dedicated opt-in trigger, publish structured results as artifacts, and never compare elapsed time from an arbitrary hosted runner to a fixed pass/fail threshold. The detailed controlled topology, CPU, and byte-cost measures are deferred to `measure-change-stream-costs`.

## Risks / Trade-offs

- [Container runtimes are absent or misconfigured locally] → Unit checks stay available without containers; integration/e2e preflight names the missing Docker API capability and contributor documentation gives Docker and Podman setup routes.
- [A replica set is initialized but not yet primary] → The fixture polls a bounded primary-election check before yielding a URI and emits actionable setup diagnostics on timeout.
- [Python 3.14-only Ruff-extra hook breaks a Python 3.13 development environment] → Provision that hook in Prek's isolated Python 3.14 environment and retain a CI job that verifies this route.
- [100% coverage leads to artificial exclusions] → Enforce branch coverage, narrowly review exclusions, and remove dead code rather than marking it unmeasurable.
- [Hosted benchmark noise produces false regressions] → Retain result artifacts and a reproducible protocol but do not make ordinary CI timing-gated.
- [Tool dependency updates change outcomes] → Pin tool versions in configuration and lock all `uv` dependency groups; update them intentionally in separate changes.

## Migration Plan

1. Add `uv` project metadata, groups, build backend, Python-version alignment, and `uv.lock`; remove Poetry configuration and `poetry.lock` through a reviewable file deletion.
2. Add Prek, formatter, type, secret, and dead-code configuration; run each configured check and correct existing violations instead of weakening rules.
3. Add pytest markers, coverage configuration, Testcontainers replica-set lifecycle fixtures, and representative tests for all three tiers.
4. Add benchmark configuration, result path conventions, contributor documentation, and correction of unverified README claims.
5. Add GitHub Actions jobs, validate the workflow files, run the local equivalents where the runtime is available, and preserve exact verification evidence in the implementation handoff.

Rollback consists of reverting this self-contained scaffold change. Because no release is published and no production database is changed, rollback has no data migration or service-state consequences.
