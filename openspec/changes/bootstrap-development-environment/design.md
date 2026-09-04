## Context

The repository currently uses Poetry metadata, has no hook configuration, and configures mypy for Python 3.12 despite declaring Python 3.13+. See [proposal.md](proposal.md).

## Goals / Non-Goals

**Goals:** Create one locked `uv` workflow and make quality defects visible before feature work.

**Non-Goals:** This change does not create tests, CI workflows, or cache behavior.

## Decisions

- Use PEP 621 metadata, dependency groups, `uv.lock`, and `uv_build` for the existing pure-Python layout. Poetry is removed so resolution has one authority.
- Make Prek the local quality entry point. The requested Ruff-extra hook uses an isolated Python 3.14 environment; package tests and type checks retain Python 3.13+.
- Correct existing quality violations instead of broad exemptions. Tool-specific exclusions require a narrow documented reason.

## Risks / Trade-offs

- [A local machine lacks Python 3.14 for the Ruff-extra hook] → Document the preflight and provision it only for the isolated hook environment.
- [Tool upgrades change results] → Pin hooks and commit the `uv` lockfile.

## Migration Plan

Replace Poetry metadata and lockfile, add the quality configuration, run all gates, and keep the refactor reversible as one tooling-only change.
