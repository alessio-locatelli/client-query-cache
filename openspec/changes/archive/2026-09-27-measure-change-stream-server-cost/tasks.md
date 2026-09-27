# Tasks

## 1. Fix the credential leak in the real-server benchmark fixture

- [x] 1.1 Replace `RealMongoDbUri`'s bare `NewType(str)` (`tests/benchmark/real_server/env.py`) with a wrapper whose `repr()`/`str()` return a redacted value; verify by intentionally failing a test that holds this fixture and confirming pytest's default traceback no longer contains the plaintext connection string.
- [x] 1.2 Update every call site that needs the real connection string (writer/reader worker processes, client construction) to use an explicit accessor for the raw value; verify the existing benchmark still connects and passes.

## 2. Add a pre-flight connectivity check before the timed benchmark window

- [x] 2.1 Add a pre-flight ping/`hello` call before the timed window starts, reusing the same client(s) the timed phases use so its warm-up transfers; verify with a test asserting the timed window excludes this call's duration.
- [x] 2.2 Re-run the benchmark warm across several consecutive runs with the pre-flight check in place and record the resulting durations; if the recorded warm durations (with the existing documented safety margin) no longer fit under `_MAXIMUM_TOTAL_DURATION_SECONDS`, update that constant to the newly measured value and record the new measurement the same way the original ceiling was documented (design.md).
- [x] 2.3 Verify `test_cache_provides_at_least_2x_benefit_over_direct_pymongo` passes consistently across several consecutive runs after 2.1-2.2.

## 3. Collect non-gating Atlas network-bandwidth evidence

- [x] 3.1 Add a new `.env` variable for the Atlas project ID, mirroring `REAL_MONGODB_URI`'s existing loading pattern; verify the benchmark reads it via `os.environ` with no new parsing dependency.
- [x] 3.2 Add a subprocess wrapper invoking `atlas metrics processes` (types: `NETWORK_BYTES_IN`, `NETWORK_BYTES_OUT`, `NETWORK_NUM_REQUESTS`, `OPCOUNTER_QUERY`; granularity `PT1M`) for the deployment's primary process, called around each of the existing cached and uncached phases; verify with a test that captures bandwidth evidence for both phases when `atlas` is available and authenticated.
- [x] 3.3 Handle a missing/unauthenticated `atlas` CLI, an Atlas API error, or an empty measurement response by logging and omitting that evidence without failing the benchmark; verify with tests simulating each case.
- [x] 3.4 Confirm the implementation never requests or reports process-level CPU measurement types from Atlas; verify by inspecting the requested metric-type list.
- [x] 3.5 Document the new `.env` variable, the `atlas` CLI prerequisite, and the non-gating nature of this evidence in `CONTRIBUTING.md`'s real-server-benchmark section.

## 4. Surface the local change-stream resource-cost comparison

- [x] 4.1 Add report logic pairing the `BALANCED` workload's raw and cache variant `container_cpu_seconds` values as an explicit change-stream CPU-cost comparison; verify via a report-validation test.
- [x] 4.2 Add report logic pairing the same workload's `direct_path_bytes_sent`/`direct_path_bytes_received` when `--direct-path-proxy` was used, and marking the comparison explicitly unavailable when it was not; verify via tests covering both cases.
- [x] 4.3 Ensure the retained report set includes one `BALANCED`-workload run with `--direct-path-proxy` enabled so the network-cost comparison has real data to show; verify the retained reports include this run.
- [x] 4.4 Document the new change-stream resource-cost comparison section in `docs/stream-cost-benchmarks.md`.

## 5. Code Quality

- [x] 5.1 Scan every edited or added test in this change (including pre-existing tests in touched files) and confirm the "Writing Tests" guidelines from `AGENTS.md` are applied, including `@pytest.mark.parametrize` where cases repeat.
- [x] 5.2 Confirm no new prose comments were added to code - all "why" explanations live in this change's specs and commit bodies.
