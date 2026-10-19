# Worker fault recovery registration v8

`config.json` is the canonical registration for this version. It remains
`pending-calibration` and has not been frozen because the observer-overhead
gate was inconclusive. The copied workload originates
from `reports/concurrent-worker-workload/v1/config.json`, SHA-256
`2057af0088101622b441f977fbc9bd78397f2e023fafd8b092cc1e74d1b6d0bc`.

V8 preserves the v7 workload, calibration fraction and recovery criterion. Its
stepdown calibration cap is 1,000 requests/second after two v7 validation
windows exceeded the write-schedule tolerance at 2,232 requests/second. V1
through v7 outcomes remain in their versioned registration notes and raw
reports. The configuration digest will be recorded by each generated
benchmark report and updated here when the registration is frozen.

## Validation and reproduction

Run these commands from the repository root. Container-backed commands require
the Testcontainers bridge setup first:

```bash
source scripts/testcontainers-bridge.sh
uv run pytest -q tests/benchmark/stream_cost/test_replica_set_topology_integration.py tests/benchmark/stream_cost/test_worker_fault_controls_integration.py
uv run -- python -m benchmarks.stream_cost.shared_cache.run --smoke --phase fault --config reports/worker-fault-recovery/v8/config.json --output benchmark-reports/worker-fault-recovery/smoke-v8.json
uv run -- python -m benchmarks.stream_cost.shared_cache.run --calibrate-baselines --fault-calibration-timeline --config reports/worker-fault-recovery/v8/config.json --output benchmark-reports/worker-fault-recovery/calibration-v8.json
uv run -- python -m benchmarks.stream_cost.shared_cache.run --fault-observer-overhead --calibration-report benchmark-reports/worker-fault-recovery/calibration-v8.json --config reports/worker-fault-recovery/v8/config.json --output benchmark-reports/worker-fault-recovery/observer-overhead-v8.json
uv run -- python -m benchmarks.stream_cost.shared_cache.run --freeze benchmark-reports/worker-fault-recovery/calibration-v8.json --fault-observer-report benchmark-reports/worker-fault-recovery/observer-overhead-v8.json --config reports/worker-fault-recovery/v8/config.json
uv run -- python -m benchmarks.stream_cost.shared_cache.run --phase fault --config reports/worker-fault-recovery/v8/config.json --output benchmark-reports/worker-fault-recovery/fault-v8.json
uv run -- python -m benchmarks.stream_cost.shared_cache.analysis --phase fault --config reports/worker-fault-recovery/v8/config.json benchmark-reports/worker-fault-recovery/fault-v8.json > benchmark-reports/worker-fault-recovery/analysis-v8.json
```

The smoke command fails unless every applicable cell injects its fault, request
counts reconcile to the offered schedule, recovery is detected and the
post-recovery correctness check passes. Calibration must be validated and its
null-fault check must pass. The observer-overhead check must pass before freeze.
Freeze records the selected timeline cadence and configuration digest.

The planned 35 fixed evidence windows take 82 minutes. Including startup,
shutdown, drain and topology setup gives an unmeasured estimate of 2.5–3 hours.
The full matrix has not run. The observer-overhead gate must pass before freeze
or evidence collection; this registration stopped as inconclusive after the
1 s retry, as required by the design.

| Check                                     | Result                            |
| ----------------------------------------- | --------------------------------- |
| Three-member topology limits and election | Passed in container-backed tests  |
| V1 through V7 attempts                    | Recorded as superseded            |
| V8 fault smoke                            | Passed: 7/7 cells recovered       |
| Baseline calibration and null-fault check | Validated; 18/18 null checks pass |
| Observer overhead and selected cadence    | Inconclusive at 1 s               |
| Frozen configuration SHA-256              | Not frozen                        |
| Full fault matrix and analysis            | Not run: overhead gate failed     |

Calibration selected 692 requests/second for steady windows and 1,000 for
stepdown windows. At 250 ms, four of six overhead comparisons exceeded the
worker-CPU limit. The 1 s retry still had two failed comparisons: direct-path
repetition 0 exceeded the request-P99 limit, and independent-path repetition 0
exceeded the worker-CPU limit. Null-fault checks passed at both cadences. The
design requires stopping after this inconclusive retry, so no freeze digest or
fault-evidence report exists for v8.

Raw smoke, calibration, observer and fault reports remain untracked under
`benchmark-reports/worker-fault-recovery/` and can be regenerated with the
commands above.
