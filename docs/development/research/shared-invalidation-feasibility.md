# Shared invalidation feasibility

[Issue #87](https://github.com/alessio-locatelli/client-query-cache/issues/87)
owns this investigation into sharing MongoDB invalidations across processes.
Shared invalidation is a research question; the supported managers each own
streams and process-local cached values.

## Reproduce the measurements

Use the repository's [contributor environment](../../../CONTRIBUTING.md).
The runner creates and removes its own single-member replica set. It requires
container CPU counters and process private-memory (USS) counters; a missing
required metric fails the run visibly.

From the repository root, configure the existing container bridge and run the
short instrumentation check:

```bash
source scripts/testcontainers-bridge.sh
uv run -- python -m benchmarks.stream_cost.multiprocess_run --smoke --output benchmark-reports/shared-invalidation/smoke.json
```

Use a new output path for each run. The smoke phase has a shortened schedule and
working set and cannot support the investment gate. The registered baseline is:

```bash
uv run -- python -m benchmarks.stream_cost.multiprocess_run --output benchmark-reports/shared-invalidation/baseline.json
```

The [frozen configuration](../../../reports/stream-cost/shared-invalidation-v1/config.json)
registers both phases' research criteria before baseline sampling. The baseline
contains 192 one-minute application windows in six counterbalanced blocks,
with additional startup, drain, and shutdown time. Each window resets the data
and spawns new workers. Raw reports remain untracked.

## Measurement scope

The runner records each worker's CPU and USS independently. The harness includes
its writer, calibration observer, and their byte-proxy threads; worker CPU
includes that worker's own byte proxy. These owners must be counted once.
MongoDB CPU is measured separately through container counters. USS denotes
private process memory. Configured cache budgets and populated cache bytes are
separate measurements and must not be interpreted as USS.

Every connected client has a dedicated byte path. Worker paths, writer traffic,
and calibration traffic remain separate in the report. Command counts come from
PyMongo command observation, including requested, completed, and failed commands.
Observed stream openings must match the path's expected ownership; reconnects
and unhealthy startup prevent a cell from qualifying.

Native managers and their raw-client controls run the same aggregate read/write
schedule at each worker count. Stream-only workers and their controls issue no
application reads and replay the same writes. Only the latter pair can estimate
removable stream cost; cache refetch savings belong to native-workload context.

Native lag captures retain six groups of 20 events, with 16 delivered events
between groups. The runner verifies 200 deliveries and cross-checks retained
lag timestamps against command-observed event timestamps. Events delivered in
bounded drain remain included. Calibration runs every 50 ms; detected clock
steps, excessive offset drift, and primary changes invalidate a window. Clock
sampling cannot exclude transients that occur between observations.

## Evidence status

The shortened instrumentation run completed for synchronous and asyncio clients,
covering raw reads, native cached reads, no-stream controls, and stream-only
consumers. These observations verify instrumentation only. Registered baseline
outcomes, the investment-gate decision, and any conditional prototype assessment
are pending under [issue #87](https://github.com/alessio-locatelli/client-query-cache/issues/87).
