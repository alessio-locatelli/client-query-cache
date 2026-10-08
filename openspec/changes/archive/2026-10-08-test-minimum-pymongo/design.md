# Design

## Context

See [proposal.md](proposal.md) for motivation and scope. `tox.ini` already defines `pymongo-min` with `uv-venv-runner`, `uv_resolution = lowest-direct`, and wheel installation. The pinned tox supports `dependency_groups`; tox-uv's installed `_installer.py` applies the resolution strategy to dependency installation. The development-environment specification already makes published metadata the sole source of the driver floor.

The active `expand-python-compatibility` change owns interpreter selection. This change adds a separate CI requirement rather than replacing its matrix requirement or changing `scripts/ci_python_matrix.py`.

## Goals / Non-Goals

**Goals:** Fit the [delta contracts](specs/development-environment/spec.md) into existing dependency and test mechanisms.

**Non-Goals:** Certifying subprocess installations that independently resolve their dependencies, or duplicating the locked suite's coverage and performance gates.

## Decisions

### Extend the existing tox environment

Load the existing `dev` dependency group only in `pymongo-min`, preserving its independent resolver and installed-wheel execution. Before pytest, retain the async-client import and add a short version preflight: parse the installed package's PyMongo requirement using `packaging.requirements.Requirement`, obtain its inclusive lower-bound specifier, and compare that version with the installed driver. Print the resolved driver and interpreter identities; fail if the driver differs. This establishes that lowest-feasible resolution actually reached the declared floor, including on reused environments. No duplicated version literal or standalone validator is needed.

Using tox's group support avoids maintaining another test-tool inventory. Because the existing resolution strategy also applies to the dev group, its tools are resolved independently of the project lockfile. Configure the minimum lane's install command with `--upgrade` so uv re-resolves already installed dependencies: the dev group can install PyMongo transitively before tox installs the wheel's direct dependencies, and uv otherwise retains a satisfying newer driver despite `lowest-direct`. The version preflight remains the acceptance check for the resulting environment.

Replacing the lane with a manual downgrade of `.venv` would preserve locked test tools but require preventing later `uv run` synchronization from restoring the driver. An ephemeral `uv run --with` overlay would avoid that mutation but require another metadata-selection path and abandonment of the existing minimum environment. Both add orchestration without an established need; neither needs a prototype for this change.

### Select existing tests that execute in the tox environment

Run pytest over `tests/synchronous/test_collection.py`, `tests/asynchronous/test_collection.py`, `tests/test_cached_cursors.py`, and `tests/test_bound_sessions.py`. These exercise the six read methods, eligibility and invalidation, native cursor validation, batching, clone/rewind, cleanup, cancellation, and effective sessions against the shared disposable replica-set fixtures. Tests invoke the installed library directly, so the preflight's driver identity applies to their operations.

Running only the import cannot protect these behaviors. Repeating the complete suite would add unrelated tooling and benchmark work; installed-package and example tests create child environments that would need separate constraints to establish minimum-driver evidence. The selected cases avoid those installations and retain existing parametrization. No new library-behavior test copies are planned. Task 1.2 checks collection and execution at the minimum; expanding the unrelated tiers requires no investigation here.

### Add one job to the existing PR workflow

Use a `pymongo-min` job in `.github/workflows/test.yml`, with the existing Python scope condition and quality prerequisites, shared toolchain setup, locked outer synchronization, and `just test-pymongo-min`. Run it on the exact development interpreter with a 20-minute timeout. Include its result in `python-compatibility` using the existing explicit failure-propagation pattern. Add `tox.ini` to Python path selection. Preserve failure-log retention for this job and keep its artifacts distinct from matrix artifacts.

The new Just recipe sources `scripts/testcontainers-bridge.sh` before invoking `uv run -- tox run -r -e pymongo-min`. Allow the required Docker/Testcontainers variables into the tox environment for host Podman use. Extend the contributor testing instructions with this command and its tested scope.

A driver-by-Python matrix would test more combinations but multiply package/test work. The existing interpreter matrix keeps its locked-driver coverage, while one additional job addresses the identified driver-floor gap. A separate workflow would duplicate triggers and gate wiring. Neither alternative requires further research; task 2.1 verifies the chosen job's real execution and failure propagation.

## Risks / Trade-offs

- A transitive requirement can exclude the floor despite successful resolution. The version preflight rejects that result; task 1.2 must report the incompatibility rather than silently increasing the floor.
- A previously import-only command now needs MongoDB. The shared host bridge and contributor command supply the established disposable-runtime path.
- CI adds one wheel environment and one focused database-test run per applicable PR, with dependency installation and MongoDB startup expected to dominate added cost. Task 1.2 records elapsed time. Production hot paths are unchanged, so runtime profiling is unnecessary.
- An unexpected job skip must not pass the aggregate gate. Its existing result checks extend to this dependency; quality prerequisites remain independently required.

## Migration Plan

Deliver the tooling changes through the existing PR process. Reverting the implementation restores the previous minimum environment and gate wiring; no package API, published version constraint, live repository setting, or release procedure needs migration.
