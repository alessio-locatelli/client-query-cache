# Proposal

## Why

[Issue #194](https://github.com/alessio-locatelli/client-query-cache/issues/194) identifies a gap between the declared PyMongo minimum and recurring behavioral validation. The existing minimum-version environment checks an import, while the database-backed PR tests use the lockfile's driver selection.

## What Changes

- Extend minimum-driver validation to exercise existing synchronous and asyncio read, cursor, and session behavior.
- Make that validation a required part of the existing PR workflow, independently of lockfile freshness.
- Provide a reproducible contributor command through the existing command surface.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `development-environment`: Strengthen the existing minimum-PyMongo check from import availability to behavioral compatibility.
- `continuous-integration`: Require the minimum-driver result alongside existing locked-driver validation.

## Impact

The implementation affects `tox.ini`, `justfile`, `.github/workflows/test.yml`, CI path selection and its regression cases, and the contributor testing instructions. Public dependency bounds, API behavior, release acceptance, and dependency-update ownership remain outside this change.
