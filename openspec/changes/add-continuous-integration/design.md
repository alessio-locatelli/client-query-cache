## Context

The development and test bootstrap changes provide the commands that CI must execute. This change makes those commands authoritative on GitHub Actions.

## Goals / Non-Goals

**Goals:** Verify lock consistency, quality, packaging, coverage, and database-backed behavior in CI.

**Non-Goals:** This change does not publish releases or make benchmark timing a merge gate.

## Decisions

- Use separate fail-fast quality/build, unit/coverage, and Docker integration/e2e jobs to make failures attributable.
- Run `uv sync --locked`; a lockfile mutation is a failure, not an automatic update.
- Test the package on CPython 3.14, matching the package baseline and the Ruff-extra hook interpreter.
- Upload coverage and failure diagnostics that exclude documents, credentials, queries, and resume tokens.

## Risks / Trade-offs

- [Hosted Docker differs from local Podman] → Docker is the documented CI baseline; local Podman support remains a contributor convenience.
- [Slow database jobs delay feedback] → Keep unit/quality jobs independent and fail fast.

## Migration Plan

Add validated workflow files only after their local equivalents exist; keep release publication deliberately out of scope.
