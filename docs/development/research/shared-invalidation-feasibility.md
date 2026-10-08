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

Worker deadline waits sleep for at most one second at a time. Their wakeups are
included in worker CPU on every path, including controls. The application
schedule and its 50 ms lateness tolerance remain fixed.

## Recorded baseline attempt

The registered run at revision
`9954d9fc9ae4f3d09cd0616b0859c1dd12d7abc5` stopped in its second window.
The synchronous, one-worker idle raw-client control completed; the matching
native-manager window failed with `application schedule exceeded tolerance`.
The runner rejected that window under the registered 50 ms tolerance. The
available error does not identify whether start or end scheduling was late,
or establish why the worker was delayed. A diagnostic repeat of the same cell
identified a 60.0 ms late wakeup at the end of its single 60-second sleep.
A standalone timer comparison measured 55.7 ms lateness with one sleep and
0.9 ms with one-second waits; CPU over the minute was respectively 0.2 ms and
9.3 ms. These diagnostics are excluded from baseline inference.

The delay is consistent with Linux's timeout-dependent timer slack:
[epoll uses the slack estimate](https://github.com/torvalds/linux/blob/e557793799c5a8406afb08aa170509619f7eac36/fs/eventpoll.c#L1764),
whose [calculation](https://code.googlesource.com/linux/torvalds/linux/+/e557793799c5a8406afb08aa170509619f7eac36/fs/select.c)
allows 0.1% of the timeout for ordinary tasks. Bounding individual sleeps avoids
a minute-long timeout without changing system settings or accepting late work.
Repeating the native idle cell with bounded waits completed with 1.5 ms end
lateness and 0.08 worker CPU seconds over the minute.

Configuration SHA-256:
`fce88933afd2354f2f37699f10d1ede9d5b3ba82e34b454061ad8a1f7886b065`.

Evaluate retained baseline evidence with:

```bash
uv run -- python -m benchmarks.stream_cost.shared_invalidation_decision benchmark-reports/shared-invalidation/baseline.json
```

| Comparison         | Complete matched blocks | Outcome      |
| ------------------ | ----------------------- | ------------ |
| Synchronous idle   | 0/6                     | Inconclusive |
| Synchronous active | 0/6                     | Inconclusive |
| Asyncio idle       | 0/6                     | Inconclusive |
| Asyncio active     | 0/6                     | Inconclusive |

The investment gate is inconclusive because no registered stream-only/control
comparison is complete. A shared-delivery prototype is not justified by this
attempt. This is an incomplete measurement, not evidence that duplicated stream
cost is below the investment threshold. A fresh registered run must establish
the gate after the scheduling correction; the incomplete attempt remains
retained under [issue #87](https://github.com/alessio-locatelli/client-query-cache/issues/87).
No supported-manager saving, coordination benefit, or universal deferral follows
from these observations.

The shortened instrumentation run completed for synchronous and asyncio clients,
covering raw reads, native cached reads, no-stream controls, and stream-only
consumers. It also completed after rebasing onto the merged stream-startup
coordination implementation. These observations verify instrumentation only.
Conditional prototype work and the final transport assessment remain pending
under [issue #87](https://github.com/alessio-locatelli/client-query-cache/issues/87).
