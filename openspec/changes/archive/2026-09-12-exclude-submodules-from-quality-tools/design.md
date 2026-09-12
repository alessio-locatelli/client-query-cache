## Context

The `specifications` Git submodule is outside the parent repository's ownership. Broad root tooling
must not format, report, or collect its contents.

## Decisions

Use each tool's existing configuration surface to exclude `specifications`: Prek's global exclusion,
Ruff's exclusion settings, Mypy's scoped `files` in the existing `mypy.ini`, Node-tool ignores, and
pytest's configured test root and ignore option. Root recipes and tox rely on those configurations
instead of duplicating source-path flags.

The CI workflow continues to call the root `just` recipes. No separate CI-only scope is needed.

Document the boundary in the contributor guide. Future tooling changes require a direct audit of the
tool's configuration to confirm it excludes the submodule while retaining repository-owned files.

## Validation

Audit each configured formatter, validator, linter, and pytest entry point for the exclusion, then
run the documented formatter and lint recipes. Keep the submodule working tree unchanged.
