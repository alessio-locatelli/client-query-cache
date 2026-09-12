## Why

The repository's flat package layout lets the checkout shadow an installed distribution during
development and test runs. Moving the distributable package below `src/` makes build and
installation boundaries explicit while preserving the published `mongo_client_cache` API.

## What Changes

- Move the `mongo_client_cache` package from the repository root to `src/mongo_client_cache`.
- Configure `uv_build` to build the package from `src`.
- Update project tooling and test commands so development, tox, coverage, and built-wheel checks
  continue to import the intended package.
- Make `pyproject.toml` the only maintained source of the PyMongo lower-bound version; the
  minimum-version environment derives its resolution target from that metadata.
- Preserve the distribution name and all public import paths.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `development-environment`: Contributors build and develop the project from a `src/` package
  layout instead of the current flat layout.

## Impact

Affected areas include package paths, `pyproject.toml` build and dependency metadata,
package-discovery tooling, and the test/build validation workflow. No public API, runtime
dependency range, or published distribution name changes.
