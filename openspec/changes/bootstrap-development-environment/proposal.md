## Why

The proof of concept has no single, reproducible developer setup and mixes Poetry with a Python 3.13 package target and a Python 3.12 type-checking target. Contributors need this baseline before writing or evaluating library behavior.

## What Changes

- Replace Poetry with `uv`, a committed lockfile, dependency groups, the pure-Python `uv_build` backend, and the supported `pymongo>=4.18,<5` runtime range.
- Add Prek quality hooks for repository hygiene, Ruff, Ruff-extra, Vulture, mypy, slotscheck, Prettier, and secret detection.
- Align tooling with the CPython 3.14+ support policy.

## Capabilities

### New Capabilities

- `development-environment`: Reproducible dependency, build, formatting, linting, and type-checking workflow.

### Modified Capabilities

- None.

## Impact

- Affects package metadata, lockfiles, tool configuration, and contributor commands; it does not add cache behavior.
