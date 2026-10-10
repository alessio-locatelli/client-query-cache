# Tasks

Start only after `benchmark-concurrent-worker-workload` is archived.

## 1. Topology and injection

- [ ] 1.1 Add the three-member `ReplicaSetTopology` described in [Three-member topology](design.md#three-member-topology) to `benchmarks/stream_cost/topology.py`, reusing `ResourceLimits`, the CPU and memory readers, and the startup failure messages of `IsolatedReplicaSet`. Add an integration test in `tests/benchmark/stream_cost/` that starts it, confirms through `podman inspect` (via `flatpak-spawn --host` locally) that each member has the declared limits, runs `replSetStepDown` on the primary, and asserts that a PyMongo client without `directConnection` writes to a different, newly elected primary. If limits or cleanup fail, apply the fallback in the design and record the outcome in `reports/worker-fault-recovery/v1/registration.md`.
- [ ] 1.2 Move the one-shot history-loss injection from `SharedCacheOwner.lose_history` into `benchmarks/stream_cost/faults.py`, and call it from the owner. Verify that `tests/shared_cache/test_scenarios.py::test_lost_stream_history_clears_entries_and_fences_captures` still passes unchanged.
- [ ] 1.3 Give worker processes in `worker.py` and `window.py` the control operations `sever`, `lose-history` and `stop-and-replace`. Workers use `FaultableProxy` on single-member topologies. Add tests in `tests/benchmark/stream_cost/test_shared_cache_window.py`, parametrized over the operations, asserting that a cached worker's stream reopens (`stream:opened` increments), that history loss empties its cache, and that a replacement worker becomes ready and serves its share of the schedule.

## 2. Fault phase and analysis

- [ ] 2.1 Add the per-request timeline and the 250 ms snapshot sampling from [Timelines and sampling](design.md#timelines-and-sampling), enabled only in fault windows. Add tests showing that steady-state records keep their current keys and that fault records carry one timeline entry per offered request.
- [ ] 2.2 Add the `fault` phase to the registration-driven planner and runner. It schedules each case with its topology and path set from [Cases and injection](design.md#cases-and-injection), injects at the registered offset, records primary identities around a stepdown, runs the post-recovery probe writes and reads, and marks failed setups, unrecovered trials and correctness failures separately. Add tests for planning, not-applicable paths, the failed-setup rules from the delta spec, and a deliberate stale probe read being reported as a correctness failure.
- [ ] 2.3 Add a fault mode to `analysis.py` that buckets timelines into 1 s buckets and applies the registered recovery criterion. For each case and path, it reports the median and range across repetitions of every measure in the delta spec. Add tests with synthetic timelines for recovered, never-recovered and error-free-but-slow trials.

## 3. Registration and evidence

- [ ] 3.1 Create `reports/worker-fault-recovery/v1/config.json` (status `draft`) and `registration.md` from [Fault registration](design.md#fault-registration). Run a smoke trial with `uv run -- python -m benchmarks.stream_cost.shared_cache.run --smoke --config reports/worker-fault-recovery/v1/config.json --output benchmark-reports/worker-fault-recovery/smoke.json`, and check that the before-interval P99 spread stays below the 2 × criterion. Then calibrate each topology with `--calibrate-baselines` and `--freeze`. Record the probe ranges and the frozen SHA-256 in `registration.md`.
- [ ] 3.2 Run `source scripts/testcontainers-bridge.sh`, then `uv run -- python -m benchmarks.stream_cost.shared_cache.run --phase fault --config reports/worker-fault-recovery/v1/config.json --output benchmark-reports/worker-fault-recovery/fault.json` and the fault analysis. Verify that every trial carries the frozen digest, and that failed setups are retained with their reason and never retried in place.
- [ ] 3.3 Add a "Fault trials" section to `docs/development/research/concurrent-worker-workload.md`, covering per-case results, injection methods, topology, limits and reproduction commands. Update `docs/user/operations/deployment.md` or `docs/user/operations/monitoring.md#bypass-reasons-and-stream-health` with measured recovery figures where they refine existing guidance, and update any affected `context7.json` rule. Verify every figure against the analysis output, and check that public figures name their case, topology and worker count.

## 4. Code Quality

- [ ] 4.1 Scan the entire file for edited or added tests, including pre-existing tests within the file, and ensure that the "Writing Tests" guidelines from `AGENTS.md` are applied, including test parametrization.
- [ ] 4.2 If you are Claude Code, confirm that you added no new prose to the code (all "why" explanations must go in the specs and commit bodies). OpenAI Codex is exempt from this rule.
