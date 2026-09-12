## Context

See proposal.md - Why. The full coverage recipe currently starts unit and integration pytest
processes independently, combines their data, and runs the installed-wheel end-to-end tier later.
It already owns the container-runtime environment required by database-backed tests. Covdefaults
configures branch measurement and its default coverage threshold dynamically; the recipe repeats
the threshold explicitly. CI only uploads the resulting XML file and does not consume it.

## Goals / Non-Goals

**Goals:** Run the complete current test suite once for the default coverage workflow, preserve its
runtime and coverage-integrity guarantees, and give contributors one concise, accurate starting
path.

**Non-Goals:** Change test topology, add benchmark selection policy before benchmark tests exist,
alter the public API, or add a coverage reporting service.

## Decisions

- Run bare pytest once under coverage. The suite currently has no benchmark tests, so marker
  filtering would be speculative. The installed-wheel end-to-end test uses the same session-scoped
  MongoDB fixture as integration tests, avoiding a second runtime lifecycle. A future benchmark
  change must explicitly update the coverage workflow before benchmark collection can occur.
- Retain the single shebang recipe and its Toolbx/Distrobox socket setup. It is responsible for the
  environment that lets Testcontainers reach the host runtime. Create a fresh temporary coverage
  data location for each run; one coverage process makes parallel data files, `coverage combine`,
  and an explicit erase unnecessary.
- Retain covdefaults as the coverage-policy source of truth and remove the redundant recipe-level
  threshold. Keep the production-source exclusion scan and `strict-no-cover`; they enforce separate
  integrity properties that a percentage report cannot.
- Retain the e2e test-path coverage omission because the installed-wheel behavior runs in an
  isolated subprocess that coverage does not trace. Remove its stale configuration comment instead
  of preserving an explanation that contradicts the unified test run.
- Remove non-directive justfile comments as part of the workflow cleanup; the repository records
  rationale in commits rather than executable configuration.
- Remove XML generation and CI upload because no workflow or external service consumes the file.
  Keep the existing pytest log diagnostic artifact.
- Remove the standalone CI unit-test job. The full coverage job runs the complete suite, so the
  separate job adds duplicate work without a distinct verification result.
- Make `CONTRIBUTING.md` the canonical contributor workflow. It will state the container
  prerequisites, require socket enablement before the normal `just coverage` path, and point to
  recipe discovery and direct pytest for narrower work. `AGENTS.md` and `docs/development.md` will
  link or summarize this path without reproducing a multi-command test sequence.

## Risks / Trade-offs

- [A benchmark is added and bare pytest starts collecting it] → The benchmark change must add its
  execution policy before the benchmark test lands.
- [A combined test session exposes cross-tier state coupling] → Validate unit, integration, and
  end-to-end behavior in the unified run and retain the focused recipes for diagnosis.
- [Removing XML removes a desired CI diagnostic] → CI logs and the retained pytest log remain; add
  a coverage-report consumer only if a concrete use emerges.
- [A unit failure reaches the Docker-backed job] → Pytest runs unit tests before the database-backed
  tests in the current suite; retain focused local unit testing for rapid diagnosis.

## Migration Plan

Update coverage configuration and the recipe together, then revise the contributor entry points and
CI artifact step. Validate the unified workflow in a supported container environment and confirm
that its coverage report enforces covdefaults' branch threshold. Reverting the changes restores the
prior recipes, documentation, and XML artifact without data migration.
