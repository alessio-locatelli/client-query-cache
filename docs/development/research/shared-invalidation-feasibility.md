# Shared invalidation feasibility

[Issue #87](https://github.com/alessio-locatelli/client-query-cache/issues/87)
owns this investigation into sharing MongoDB invalidations across processes.
Shared invalidation is a research question; the supported managers each own
streams and process-local cached values.

**Recommendation:** defer a shared-delivery prototype for the measured
workloads. All four complete baseline comparisons are below the registered
investment threshold. This does not rule out an opportunity on other workloads
or topologies.

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
uv run -- python -m benchmarks.stream_cost.multiprocess_run --output benchmark-reports/shared-invalidation/baseline-retry.json
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

Native-manager lag intervals resample the six capture windows separately for
each worker and active cell. Analysis enumerates all 46,656 ordered draws with
their exact multiplicity weights, adjusts lag by the initial server-clock
offset, and expands each nominal 95% percentile interval by clock uncertainty.
These intervals are descriptive, with no simultaneous coverage claim across
workers or cells; they do not establish shared-delivery safety.

Exact enumeration removes Monte Carlo noise, not bootstrap approximation or
dependence assumptions. CPU inference treats the six paired blocks as
exchangeable units. Lag inference retains whole 20-event windows and assumes
the registered 16-event separations are useful for this paced workload; those
gaps do not protect against arbitrary correlated delay.

Worker deadline waits sleep for at most one second at a time. Their wakeups are
included in worker CPU on every path, including controls. The application
schedule and its 50 ms lateness tolerance remain fixed.

## Baseline result

The complete run at revision
`e12e78c0e532c4f6c9ea571fe7c07d5c5e2c097e` retained all 192 windows as
healthy. Configuration SHA-256:
`fce88933afd2354f2f37699f10d1ede9d5b3ba82e34b454061ad8a1f7886b065`.

The environment was Fedora Toolbx on kernel `7.2.8-200.fc44.x86_64`, with an
AMD Ryzen 3 210 and eight logical CPUs. The runner used Python 3.14.6,
PyMongo 4.18.2, psutil 7.2.2, and testcontainers 4.15.0. MongoDB ran from
`mongo:8.0.4-noble` as a single-member replica set limited to two CPUs and
2 GiB; the worker and harness processes ran outside those container limits.

Evaluate the retained evidence with:

```bash
uv run -- python -m benchmarks.stream_cost.shared_invalidation_decision benchmark-reports/shared-invalidation/baseline-retry.json
```

The gate estimates removable duplication as eight-stream minus one-stream
MongoDB CPU, after subtracting each worker count's matched no-stream control.
Each comparison has six complete paired blocks. Rates use the fixed 60-second
denominator; active totals include separately measured drain CPU. The signed
basic-bootstrap bounds use `alpha=0.0125` in each tail, with the registered
Bonferroni correction over four opportunity alternatives.

| Comparison         | Mean CPU seconds/second | Lower bound | Upper bound | Outcome         |
| ------------------ | ----------------------: | ----------: | ----------: | --------------- |
| Synchronous idle   |                 0.00337 |     0.00219 |     0.00424 | Below threshold |
| Synchronous active |                 0.01095 |     0.01005 |     0.01184 | Below threshold |
| Asyncio idle       |                 0.00340 |     0.00267 |     0.00408 | Below threshold |
| Asyncio active     |                 0.01104 |     0.00957 |     0.01269 | Below threshold |

Every upper bound is below **0.05 CPU seconds/second**. The gate therefore
does not pass, and conditional tasks 2.1–2.3 are skipped: no research receiver,
coordinator, IPC fault experiment, or shared-versus-independent measurement was
built. Active-minus-idle excess is 0.00757 for sync and 0.00764 for asyncio;
event-driven cost exceeds idle polling cost here but remains below the gate.
Mean MongoDB drain CPU per active stream-only/control cell ranges from
0.018 to 0.257 ms; it is included rather than discarded.

### Native-manager context

Each document encodes to 4,135 BSON bytes. Every native worker admitted all
1,024 documents during priming. The following idle values distinguish budget
ceilings, populated cache accounting, and mean observed private memory across
six blocks. MiB uses 1,048,576 bytes.

| Model   | Workers | Total budget (MiB) | Primed cache (MiB) | Worker USS (MiB) |
| ------- | ------: | -----------------: | -----------------: | ---------------: |
| Sync    |       1 |                 64 |               4.05 |            44.75 |
| Sync    |       8 |                512 |              32.37 |           356.65 |
| Asyncio |       1 |                 64 |               4.05 |            44.88 |
| Asyncio |       8 |                512 |              32.37 |           356.76 |

Active CPU below is the six-block mean in seconds, including drain, for the
same aggregate 1,800 reads and 200 updates. Worker CPU sums child processes and
their proxies; harness CPU includes writer, calibration, and their proxies.
Worker wire bytes cover only the dedicated worker paths; writer and calibration
traffic remain separately identified in the raw report.

| Model   | Workers | Path        | MongoDB CPU | Worker CPU | Harness CPU | Worker wire (MiB) |
| ------- | ------: | ----------- | ----------: | ---------: | ----------: | ----------------: |
| Sync    |       1 | Raw control |       2.188 |      1.668 |       1.918 |             8.079 |
| Sync    |       1 | Native      |       1.671 |      1.152 |       1.928 |             0.793 |
| Sync    |       8 | Raw control |       2.194 |      1.910 |       1.875 |             8.141 |
| Sync    |       8 | Native      |       2.357 |      2.352 |       1.957 |             2.294 |
| Asyncio |       1 | Raw control |       2.163 |      2.165 |       1.878 |             8.079 |
| Asyncio |       1 | Native      |       1.668 |      1.275 |       1.927 |             0.793 |
| Asyncio |       8 | Raw control |       2.227 |      2.602 |       1.887 |             8.141 |
| Asyncio |       8 | Native      |       2.413 |      3.107 |       1.955 |             2.294 |

These native comparisons combine cached-read savings and invalidation work;
they do not estimate a shared coordinator's benefit. Sharing invalidations
would still retain duplicated cached values and per-worker delivery work.

All 108 native worker/cell captures were complete. The ranges below retain
individual worker/cell p95 estimates and the envelope of their expanded nominal
95% interval endpoints, in milliseconds. They are neither pooled intervals nor
a simultaneous confidence band, and provide no shared-delivery safety result.

| Model   | Workers | Captures | Individual p95 range (ms) | Interval endpoint envelope (ms) |
| ------- | ------: | -------: | ------------------------: | ------------------------------: |
| Sync    |       1 |        6 |                 16.7–29.1 |                        8.9–43.1 |
| Sync    |       8 |       48 |                 13.0–95.7 |                       7.1–117.7 |
| Asyncio |       1 |        6 |                 16.3–38.3 |                        7.2–52.2 |
| Asyncio |       8 |       48 |                 16.7–46.3 |                        9.4–56.7 |

### Scheduling correction

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

The incomplete original report remains at
`benchmark-reports/shared-invalidation/baseline.json`: all four opportunity
comparisons have zero complete matched blocks and are inconclusive. It is
excluded from the complete retry's inference and cannot establish a cost bound.

## Coordination assessment

This is an unvalidated design assessment of shared delivery. The baseline
measures supported managers and projected streams; it does not exercise a
coordinator, subscriber recovery, or a supported manager using shared delivery.

| Model                                 | Operating fit                                                                    | Continuity and cost assessment                                                                                                                                                                                                                                                                                        |
| ------------------------------------- | -------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Independent managers                  | Current supported choice across processes and hosts.                             | Each manager owns its stream and recovery. Local caches and their memory remain duplicated; measured stream-only costs determine whether coordination merits further work.                                                                                                                                            |
| Local coordinator with bounded queues | A small experiment for trusted children on one host.                             | Sharing upstream consumption still requires one receiver and ordered delivery per worker. A full queue must detach that subscriber without blocking others. Recovery clears its cache before ordered readiness; coordinator loss affects the whole group.                                                             |
| Sidecar with socket delivery          | A possible owner outside worker lifetimes, potentially serving several runtimes. | Requires deployment ownership, authenticated publishers and subscribers, a versioned bounded message format, reconnect semantics, and shutdown handling. Sockets alone provide no durable replay or safe cache readiness. No sidecar benefit is measured here.                                                        |
| External pub/sub or durable log       | A candidate for independent hosts when an additional service is acceptable.      | A product proposal must select and verify ordering, retention, subscription recovery, authorization, and outage behavior. Continuity without replay requires clearing and a fresh ordered certificate; retained replay can help only while the required history remains available. No broker is selected or measured. |

Python's [multiprocessing queues](https://docs.python.org/3.14/library/multiprocessing.html#pipes-and-queues)
serialize messages with pickle and use feeder threads. Their trust boundary
must exclude untrusted publishers. Queue contents must be drained or explicitly
abandoned before joining publishers; forcefully terminated queue users can
corrupt the transport. A future implementation must account for those buffers,
shutdown deadlines, and queue replacement during recovery.

### Conservative continuity model

Every subscriber would begin unavailable, with cached lookup and admission
disabled. An ordered readiness certificate would enable it only after clearing
the affected database. Certificates would record an upstream observation and
the last published sequence; subscribers could renew a three-second local lease
only after applying that sequence. A coordinator heartbeat would not demonstrate
that the upstream watch was progressing. The lease would bound local detection
of silent failure, not MongoDB commit-to-invalidation delay.

| Failure                                               | Required local response and recovery                                                                                                                                                                             |
| ----------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Coordinator death, stalled watch, or stalled receiver | Check lease expiry on each lookup and admission; bypass and disable admission when it expires. Clear before accepting fresh ordered readiness.                                                                   |
| Sequence gap, reordered event, or duplicate envelope  | Treat unexpected sequence as lost continuity; disable cache use and clear. Establish a new subscription rather than continuing the old sequence.                                                                 |
| Queue overflow or paused subscriber                   | Detach that subscriber, discard its subscription, and recover with a new queue and subscription epoch. Other subscribers continue independently.                                                                 |
| Late join, rejoin, or changed coordinator epoch       | Start unavailable, clear, and require readiness for the new epochs; reject delayed messages from the old subscription.                                                                                           |
| Lost MongoDB history or database invalidation         | Announce upstream uncertainty to subscribers, stop certificates, and clear affected state before re-establishing the upstream watch and ordered readiness. Lease expiry covers missed uncertainty notifications. |
| Database read spanning uncertainty and recovery       | Reject admission under the earlier availability generation, including when availability has returned before the read completes.                                                                                  |

The existing cache core advances its availability generation on state changes
and checks that generation during both identity and namespace admissions. A
shared receiver would still have to enforce lease expiry and sequence/epoch
validation around those local operations. Healthy lookups should consult local
state and time without IPC or database calls. Asyncio receivers must offload
blocking transport operations; mixed groups need the same ordering rules. These
are proposed obligations, not fault-test results.

Automatic fallback to independent native managers remains an integration
question under [issue #87](https://github.com/alessio-locatelli/client-query-cache/issues/87).
A switch would need explicit ownership of the outgoing shared subscription and
incoming native stream, unavailable/clear transitions, and fresh readiness before
cache use resumes. Native managers cannot safely inherit a coordinator heartbeat
as proof of continuity. Local cached values remain per process in either mode;
sharing invalidations does not remove their memory cost.

The measurements cannot establish behavior on sharded deployments, independent
hosts, other database counts, or different event and working-set sizes. Any
supported shared mode needs a separate proposal under
[issue #87](https://github.com/alessio-locatelli/client-query-cache/issues/87),
including public opt-in semantics, native-manager integration, transport trust,
deployment ownership, and recovery costs.
