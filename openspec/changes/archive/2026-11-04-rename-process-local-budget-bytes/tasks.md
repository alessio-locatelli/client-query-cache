# Tasks

## 1. Rename

- [x] 1.1 Implement the cache-core delta's configuration and snapshot naming contract across `_core/manager.py`, `lru.py`, `snapshots.py`, `native.py`, `shared.py` and the shared coordinator's observation producers and readers. Update maintained executable callers using `rg -n 'shared_budget_bytes' src tests benchmarks research examples docs/user README.md context7.json`; preserve historical reports and archives. Retain the version-1 stream-cost report's serialized budget field independently of the renamed snapshot attribute, and validate the retained reports against its original schema. Extend configuration/inspection and shared-observation tests to verify renamed construction, field-specific validation, removed keyword and attribute behavior and observation round trips. Update affected API-reference examples and the unreleased changelog according to its editing policy.

## 2. Code Quality

- [x] 2.1 Scan the entire file for each edited or added test, including pre-existing tests within that file, and apply the `AGENTS.md` Writing Tests guidelines, including parametrization; verify the resulting test diff against those guidelines.
