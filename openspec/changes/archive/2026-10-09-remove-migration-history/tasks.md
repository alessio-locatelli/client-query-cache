# Tasks

## 1. Repository content

- [x] 1.1 Delete `tests/test_removed_prototype_api.py` and its `.vulture_whitelist` entry.
- [x] 1.2 Rename the `migrated`/`unmigrated` identifiers and the "incrementally" test name in `tests/synchronous/test_collection.py` and `tests/asynchronous/test_collection.py`, keeping the pair identical.
- [x] 1.3 Change the `$id` URNs in `benchmarks/stream_cost/schemas/*.json` to `urn:client-query-cache:...`.
- [x] 1.4 Verify that a search of tracked files outside `openspec/changes/archive/` and committed benchmark evidence finds no prototype-migration or former-name references, and that `just lint` and `just tests_and_coverage` pass.

## 2. Archive

- [x] 2.1 After review, archive the change so that it retires `openspec/specs/prototype-recovery/` per the design.
