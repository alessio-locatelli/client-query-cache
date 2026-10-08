# Proposal

## Why

[Issue #195](https://github.com/alessio-locatelli/client-query-cache/issues/195) questions the package's patch-level Python floor. Python 3.15 is also available for compatibility testing, but the current CI matrix cannot reach it while development remains on 3.14, and the README advertises only a minimum.

## What Changes

- Relax published Python eligibility to `>=3.14`, subject to compatibility evidence on the earliest eligible interpreter.
- Exercise Python 3.15 independently of the stable development selection.
- Show supported Python release lines through a PyPI-backed README badge and aligned package metadata and guidance.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `development-environment`: Separate installation eligibility, explicit support declarations, and development selection.
- `continuous-integration`: Apply compatibility coverage to both existing matrix consumers.
- `public-library-documentation`: Define the badge's metadata source and release scope.

## Impact

Package metadata and its lockfile, runnable example eligibility, matrix selection and its regression tests, and existing installation and contributor guidance are affected. The cache API and runtime implementation are outside this change. Support for Python below 3.14 and additional interpreter variants is outside scope.
