# Tasks

## 1. Preserve count options

- [x] 1.1 Add parametrized sync and async native-error regressions for `limit=0`, `limit=None`, `skip=None`, and `hint=None` across cold, warm, and extra-option bypass reads; verify omitted skip and zero skip reuse the same entry in both call orders.
- [x] 1.2 Match PyMongo's kwargs option handling in both count signatures, remove the public omission token from the API, and use private cache-shape normalization; verify native kwargs remain unchanged and supported options stay cacheable.
- [x] 1.3 Describe native PyMongo/MongoDB error propagation and equivalent skip entry reuse in the guide and unreleased changelog.

## 2. Code Quality

- [x] 2.1 Scan both edited collection test files for compliance with AGENTS.md Writing Tests guidelines, including parametrization.
- [x] 2.2 Confirm no new code prose for Claude Code (inapplicable: implemented by Codex).
