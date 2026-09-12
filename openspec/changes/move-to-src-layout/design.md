## Context

See proposal.md - Why. The package currently lives at the repository root and `uv_build` declares
an empty module root. Tox deliberately installs a non-editable wheel, while developer commands use
the synchronized editable project; tests, Vulture, and the coverage exclusion guard also refer to
the current root package path.

## Goals / Non-Goals

**Goals:**

- Make the source tree unimportable from the repository root unless the project has been installed.
- Keep editable development imports, non-editable tox imports, wheel contents, and public import
  paths consistent.
- Keep every path-sensitive quality and coverage check aimed at the production package.

**Non-Goals:**

- Renaming the distribution or Python package.
- Changing public APIs, dependencies, test-tier behavior, or release publishing workflow.
- Moving tests below `src/`.

## Decisions

### Place only the distributable package below `src/`

Move `mongo_client_cache/` to `src/mongo_client_cache/` and set the build backend module root to
`src`. Tests remain a root-level package so pytest can collect their shared fixtures and test-module
imports as it does today. This preserves the public namespace while ensuring a Python process
started from the checkout cannot find production code by accident.

Keeping the flat layout was considered, but it permits a root-path insertion to shadow a wheel.
Moving tests into `src/` was rejected because tests are not distributable package contents and doing
so would blur the source/test boundary without improving import isolation.

### Let the layout enforce tox's installed-package boundary

After the move, pytest's default `prepend` mode may add the repository root for test imports, but
that root no longer contains `mongo_client_cache`. Tox's non-editable wheel therefore remains the
only provider of production imports. Remove the tox-only `--import-mode importlib` override because
the source layout, rather than a pytest implementation mode, enforces the intended boundary.

Retaining the override was considered, but it would be redundant and would conceal that the layout
itself is the protection against source-tree shadowing.

### Derive the minimum PyMongo environment from dependency metadata

Keep the version literal only in the published PyMongo dependency declaration. Replace the tox
environment's exact PyMongo dependency with tox-uv's `lowest-direct` resolution strategy, so it
installs the project's declared direct-dependency floor while preserving the environment's existing
non-locked, wheel-install test purpose. Specifications describe the derivation contract, not the
current version.

Keeping a matching pin in tox was considered, but it creates two independently maintained version
values and can silently test an obsolete floor after a dependency upgrade. Parsing project metadata
in a custom test command was rejected because tox-uv already provides the resolution behavior
without introducing bespoke configuration logic.

### Update every path-sensitive tool and preserve lock consistency

Update explicit production-directory references, including Vulture and the coverage exclusion scan,
to use `src/mongo_client_cache`. Let tools that already recursively inspect the repository continue
to do so. Retain the committed lockfile because a build-backend module-root change does not alter
dependency resolution; verify that `uv lock --check` still succeeds.

## Risks / Trade-offs

- [A stale root-package path leaves source out of a quality or coverage check] → Search tracked
  configuration and commands for the old path, then run the affected gates.
- [A build configuration error omits the package from an artifact] → Build source and wheel
  distributions and install each in a clean environment before importing its public API.
- [A command relies on implicit checkout imports] → Run the documented editable developer command
  and non-editable tox command after the move.
- [The minimum-version environment stops exercising the published floor] → Verify the resolved
  PyMongo version equals the lower bound declared in project metadata before running its API probe.

## Migration Plan

1. Move the tracked package directory and update build/tool configuration in one focused change.
2. Confirm the lockfile remains valid, then run formatting, linting, unit tests, the derived
   minimum-version and standard tox environments, and source/wheel installation checks.
3. Revert the focused change to restore the root package layout if a downstream tool cannot consume
   the `src/` layout.
