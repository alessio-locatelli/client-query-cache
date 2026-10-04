# Tasks

## 1. Mixed real-server workload

- [x] 1.1 Add shared stress fixtures and parametrized sync/async tests with four readers, hot/cold collections, external CRUD, processed-event revision assertions, per-reader liveness and substantial progress observed at every CRUD phase boundary, and verified positive/negative cache hits. Verify each default run performs two cycles of 40 writes and 320 checkpoint reads per cycle.
- [x] 1.2 Add a positive `--stress-cycles` pytest option and document default/longer-run commands in `docs/development/concurrency-stress-tests.md`, linked from contributor testing guidance. Verify the documented default and extended commands execute the workload under pytest-timeout.

## 2. Controlled admission and recovery races

- [x] 2.1 Add parametrized identity/namespace reads paused after a real database response while background readers run. Process a real invalidation before release; verify the old in-flight value returns without admission and the following read misses and retrieves the new version.
- [x] 2.2 Inject stream disconnection and lost resume history, gate successful reopening during active readers, and verify unchanged hit counts and empty cache storage during uncertainty plus rejection of the paused read after recovery. Cover both execution models and document the recovery scenario alongside the workload.

## 3. Code Quality

- [x] 3.1 Scan all added or edited test files for compliance with AGENTS.md, including parametrization, fixture cleanup, explicitly armed watch-boundary recovery injection, semantic database typing, and removal of unused helper code.
