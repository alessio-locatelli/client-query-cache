## Context

The repository currently uses Poetry metadata and already has a `.pre-commit-config.yaml` with pinned hygiene, Ruff, mypy, slotscheck, codespell, and typos hooks. It also configures mypy for Python 3.12 despite declaring Python 3.13+. See [proposal.md](proposal.md).

## Goals / Non-Goals

**Goals:** Create one locked `uv` workflow and make quality defects visible before feature work.

**Non-Goals:** This change does not create tests, CI workflows, or cache behavior.

## Decisions

- Use PEP 621 metadata, dependency groups, `uv.lock`, and `uv_build` for the existing pure-Python flat layout. Configure `[tool.uv.build-backend]` with `module-root = ""` so `uv_build` discovers the repository's `mongo_client_cache/` package. Poetry is removed so resolution has one authority. Declare `pymongo>=4.18,<5`: this project starts from scratch, so its lower bound is the latest published PyMongo release rather than the oldest version that happens to work, while [PyMongo 4.13 already made its native async API generally available](https://www.mongodb.com/docs/languages/python/pymongo-driver/current/reference/release-notes/); verify the lower bound rather than assuming a lockfile's latest resolution proves it.
- Make Prek the local quality entry point by migrating the existing hook configuration. Preserve its hygiene, Ruff, mypy, slotscheck, codespell, and typos coverage; replace the Poetry-specific validation with equivalent `uv` project validation because Poetry is removed. The requested Ruff-extra hook uses an isolated Python 3.14 environment; package tests and type checks retain Python 3.13+.
- Correct existing quality violations instead of broad exemptions. Tool-specific exclusions require a narrow documented reason.

## Risks / Trade-offs

- [A local machine lacks Python 3.14 for the Ruff-extra hook] → Document the preflight and provision it only for the isolated hook environment.
- [Tool upgrades change results] → Pin hooks and commit the `uv` lockfile.

## Migration Plan

Replace Poetry metadata and lockfile, add the quality configuration, run all gates, and keep the refactor reversible as one tooling-only change.
