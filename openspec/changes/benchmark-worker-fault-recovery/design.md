# Design

## Context

After `benchmark-concurrent-worker-workload`, the harness in `benchmarks/stream_cost/shared_cache/` is registration-driven and runs `direct` and `independent` worker groups under a frozen steady-state workload (`reports/concurrent-worker-workload/v1/`). The existing fault tooling is limited:

- `FaultableProxy` in `owner.py` can pause, resume or sever the TCP connections of one process's proxy.
- `SharedCacheOwner.lose_history` in `coordinator.py` makes the next stream reopening fail with `ChangeStreamHistoryLost` (code 286) by patching the supervisor's `_open_stream` once, the same injection pattern used by `tests/stress/helpers.py`.
- `IsolatedReplicaSet` in `topology.py` starts a single member, and clients use `directConnection=true`, so failover is impossible.
- Worker samples keep latencies but not the time at which each request completed, so results can't be split into the intervals before, during and after a fault.

## Goals / Non-Goals

**Goals:**

- Timed, repeated and descriptive recovery evidence for each case, for direct and independent groups of four asyncio workers.
- Reuse the steady-state workload shape so that fault behaviour can be read alongside steady-state results.

**Non-Goals:**

- Shared-cache owner faults, which the shared prototype's safety scenarios already cover.
- Network partitions between members, rolling restarts, sharded clusters and multiple hosts.
- Confidence intervals or gates; five repetitions support description only.

## Decisions

### Fault registration

`reports/worker-fault-recovery/v1/` copies the data, hot set, read and write mix, per-worker concurrency and execution model from `reports/concurrent-worker-workload/v1/config.json`. It cites that file's digest and fixes the following:

| Parameter           | Value                                                                                                                                                                                                 |
| ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Workers             | 4 asyncio                                                                                                                                                                                             |
| Repetitions         | 5 per case and path; path order alternates by repetition                                                                                                                                              |
| Window              | 20 s before the fault, injection, then 40 s after it                                                                                                                                                  |
| Intervals           | Before: the 10 s ending at injection. During: from injection to recovery. After: the 10 s following recovery                                                                                          |
| Recovery criterion  | First 1 s bucket at or after which every later bucket has no failed reads and a request P99 within 2 × the before-interval P99. Unrecovered by the window end means the trial reports "not recovered" |
| Post-recovery check | 16 hot probe keys written after recovery; each cached worker must process their invalidations within the drain, then read the new revisions                                                           |
| Offered rate        | Frozen by the registered baseline calibration rule at four workers on each case's topology                                                                                                            |

The 2 × P99 factor and the 1 s buckets are chosen so that ordinary scheduling jitter in the steady-state run doesn't register as unrecovered. A tighter factor would make recovery depend on noise. Task 3.1's smoke run checks this against the before-interval spread. Changing these values requires a new registration version.

### Cases and injection

| Case              | Topology      | Injection                                                                                                                           | Paths                                 |
| ----------------- | ------------- | ----------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| `connection-loss` | single member | Every worker's `FaultableProxy` severs all of its connections at the same moment                                                    | direct, independent                   |
| `stepdown`        | three members | `replSetStepDown` on the primary, using the server defaults for step-down and catch-up periods                                      | direct, independent                   |
| `history-loss`    | single member | Each cached worker arms the one-shot `ChangeStreamHistoryLost` reopening failure, then severs its own proxy to force a reopening    | independent; direct is not applicable |
| `worker-restart`  | single member | `SIGKILL` of worker 0, followed by an immediate replacement with the same spec that primes before serving its share of the schedule | direct, independent                   |

Alternatives for connection loss and history loss:

| Alternative                                                           | Pros                                                                                                             | Cons                                                                                                                                            | Unknowns                                                                                           |
| --------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Proxy severing and a one-shot reopening failure (chosen)              | Reuses tested injection; real TCP teardown, so PyMongo reconnection and the manager's recovery code run for real | History loss is simulated at the reopen call rather than produced by the server                                                                 | None                                                                                               |
| Server `failCommand` failpoints (`closeConnection`, `errorCode: 286`) | Server-produced errors                                                                                           | Needs `enableTestCommands`, which changes the measured server configuration; filtering stream resumes from reads relies on `appName` and timing | Whether a failpoint can target only the resume `aggregate` without hitting the initial stream open |
| Real oplog rollover                                                   | Fully real history loss                                                                                          | The minimum oplog size (990 MB) makes rollover slow and dominated by write volume                                                               | Time to roll over on a 2 GiB member                                                                |

No further research is needed. The shared history-loss helper moves to `benchmarks/stream_cost/faults.py`, where the shared-cache owner and the worker processes both call it, so the injection isn't duplicated.

### Three-member topology

Add a `ReplicaSetTopology` that starts three `mongo:8.0.4-noble` members with `network_mode="host"` on three distinct loopback ports. Each member gets 1 CPU and 1 GiB. Members advertise `127.0.0.1:<port>`, which resolves the same way inside the containers and in the Toolbx harness, so clients can use replica-set discovery without `directConnection`. Byte proxies are not used on this topology, and the stepdown case reports no MongoDB wire bytes.

| Alternative                                             | Pros                                                               | Cons                                                                                                      | Unknowns                                                                                                                  |
| ------------------------------------------------------- | ------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Host networking with loopback member addresses (chosen) | One address works from containers and harness; no hostname mapping | Binds host ports, so only one topology can run at a time; requires host networking to be available        | Whether rootless Podman applies CPU and memory limits and Ryuk cleanup unchanged under host networking; task 1.1 verifies |
| Bridge network with container hostnames                 | Isolated ports                                                     | The harness can't resolve container hostnames without editing `/etc/hosts`                                | —                                                                                                                         |
| Per-member byte proxies with advertised proxy ports     | Keeps wire-byte accounting                                         | Members must advertise the proxies' addresses, which couples the replica set configuration to the harness | —                                                                                                                         |

If task 1.1 shows that host networking drops resource limits, the fallback is a bridge network plus PyMongo's `directConnection=false` with `host.containers.internal` member addresses and a harness-side `/etc/hosts` check. That changes only this section and task 1.1.

### Timelines and sampling

Fault windows make each worker keep, for every request, the scheduled offset, the completion offset and the error type, using the window's shared monotonic start. Cached workers also sample their manager snapshot every 250 ms, recording hits, misses, bypass reasons, entry count and stream health. Steady-state windows keep their current, smaller record, so steady-state results and run cost stay unchanged.

Recording every request costs about 24 bytes for each of roughly 80,000 requests per worker per window, which is negligible. The 250 ms snapshot follows the measured v4 observer overhead: 200 ms PSS sampling had no measurable effect on request P99.

## Risks / Trade-offs

- [Three members at 1 CPU each plus four workers load the 8-CPU host more than steady state does] → Each case's topology is calibrated separately, and the stepdown case is compared only with itself.
- [The 2 × P99 recovery criterion is a judgement] → It is preregistered, and the report includes the before-interval spread and the full bucketed timeline, so readers can apply a stricter rule.
- [Simulated history loss skips the server-side cause] → The report labels the injection method.
- [Five repetitions give wide ranges] → The report shows the median and the full range, without confidence claims.
