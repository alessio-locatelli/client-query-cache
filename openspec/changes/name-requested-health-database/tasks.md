# Tasks

## 1. Implementation

- [x] 1.1 Rename the `StreamHealthSnapshot` field in `src/client_query_cache/_core/stream_health.py`, removing the comment the new name makes redundant, and update every reference. Verify that `just lint` passes.
- [x] 1.2 Add a parametrized test to `tests/synchronous/test_manager.py` and `tests/asynchronous/test_manager.py` covering an empty and an unknown name on an open and a closed manager. Verify that `just tests_and_coverage` passes.

## 2. Documentation

- [x] 2.1 Describe the field in the stream-health paragraph of `docs/user/operations/monitoring.md`, add a Context7 rule, and add a breaking-change entry to `CHANGELOG.md` under Unreleased. Verify that `just lint` passes.
