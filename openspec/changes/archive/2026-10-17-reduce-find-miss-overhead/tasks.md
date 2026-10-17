# Tasks

## 1. Find execution cost

- [x] 1.1 Add a `find-cost` command to `research/invalidation_scope/benchmark.py`, reusing its seeded feed and replica topology. Verify cold reads each issue one find and warm reads issue none; measure direct, cold, exact, and compatible phases without timing invalidation or profiling. Capture a separate cold profile and record baseline and candidate CPU/wall measurements, churn results, and reproduction commands in `docs/development/research/invalidation-scope.md`.
- [x] 1.2 Implement design decision 1 in both execution models and the core lookup boundary. Extend the prepared-shape tests to verify discriminator object reuse, matching hashes, and family metadata for supported and exact-only limits; retain family-collision and native-cursor regression coverage.
- [x] 1.3 Implement design decisions 2 and 3 in cursor capture and its remote adapter. Update snapshot-size boundary and single-encoding tests, and verify codec round trips with non-leading `_id`, native aggregation field order in both cursor APIs, mutation isolation, complete consumption, and stale/oversize admission cases.

## 2. Code Quality

- [x] 2.1 Scan each entire edited test file against the Writing Tests rules in `AGENTS.md`, including parametrization.
- [x] 2.2 Confirm Claude-specific prose restrictions are inapplicable: implemented by Codex.
