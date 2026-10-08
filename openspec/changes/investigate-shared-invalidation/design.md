# Design

## Context

See [proposal.md](proposal.md) for motivation and scope, and the [delta](specs/stream-cost-benchmarking/spec.md) for acceptance contracts.

The two `src/client_query_cache/*/streams.py` implementations own a supervisor per database and directly call the shared `route_change_event()` router. `CacheCore.set_database_available()` advances an availability generation when state changes; admission captures that generation. These are useful research seams without changing the supported managers.

`benchmarks/stream_cost/` already provides an isolated single-member replica set, container CPU collection, clock calibration, a direct-path byte proxy, and command-level `getMore` observation. `measurement.py` measures CPU of its calling process, so it cannot account for children by itself. The current runners do not compare worker counts.

Manager startup, retry, and shutdown follow the [change-stream coherency contract](../../specs/change-stream-coherency/spec.md). Record the measured revision and require successful startup and warmup. The canonical coherency spec requires a stream per manager/database; a future supported shared mode would need an explicit opt-in contract revision. This research does not modify that requirement.

## Goals / Non-Goals

**Goals:** Separate duplicated stream overhead from duplicated cache occupancy and test a conservative continuity model at the cache-core boundary.

**Non-Goals:** Generalize single-host results to sharded clusters or independent hosts, or treat a primitive benchmark as complete manager integration. The broader scope boundary is in the proposal.

## Decisions

### Reuse the benchmark package with spawned workers

Add `multiprocess_run.py` and a focused `shared_invalidation.py` research module under the existing benchmark package. Keep orchestration, data generation, metrics, and report handling there; reuse the topology, command listener, calibration, and byte-proxy helpers. Create PyMongo clients inside spawned children, close managers before clients, and give child startup and shutdown bounded deadlines.

Use `psutil` for each process's CPU deltas and private memory (USS), already available through the development group's `pytest-xdist[psutil]`; declare it directly in that group when the benchmark imports it. Parent/harness measurements remain separate. Do not sum RSS into a claimed private-memory total.

Extending existing runners would avoid an entry point but entangle their single-process report assumptions with worker coordination. A separate benchmark package would isolate the experiment but duplicate topology and measurement code. Neither alternative needs further research; task 1.1 implements the selected layout.

### Freeze a small baseline protocol

Use one active database with two cached collections, one and eight long-lived workers, and homogeneous sync and asyncio groups. Each worker primes the same 1,024 documents with approximately 4 KiB payloads under the current default budget. Document the encoded sizes and observed admissions. Use one fixed aggregate schedule, partitioned evenly among workers; changing worker count must not multiply application operations.

Collect six counterbalanced blocks on the same isolated topology, resetting data and child/cache state between windows. Each cell has a matched raw-client no-stream control and native-manager path:

| Window                  | Timed application work                                      | Purpose                                                      |
| ----------------------- | ----------------------------------------------------------- | ------------------------------------------------------------ |
| Idle                    | 60 seconds, no reads or writes after priming                | Isolate polling overhead and populated memory                |
| Read-heavy with updates | 1,800 reads and 200 relevant updates spread over 60 seconds | Observe hit/miss/bypass costs and delivered invalidation lag |

Keep `max_await_time_ms=1000`, client options, data-generation seed 87, and resource limits fixed. Issue reads at offsets `i/30` seconds for `i=0..1799` and updates at `0.3*i` seconds for `i=0..199`, partitioning reads evenly among workers. Count read outcomes and require every worker to observe the scheduled invalidations by a separate bounded drain phase. Include drain cost separately. Record requested/completed/failed wire commands, actual stream ownership, per-process CPU/memory, MongoDB CPU, populated cache bytes, and per-worker latency distributions. Collect dedicated MongoDB-path bytes per client and sum only those paths; writer/observer paths are identified separately.

Add matched stream-only cells for both idle and active windows at both worker counts and execution models. Workers open the native projected database streams and consume events without caches or application reads. Their no-stream controls keep the same number of connected clients and replay the same writer schedule; both paths start from identical data. Each watching worker must consume all 200 scheduled updates in an active cell. Thus the active comparison isolates stream delivery work without avoided cache refetches. Native-manager active measurements remain workload context, not stream-only cost evidence.

A thread-only test would miss process memory and IPC; a broad matrix of databases, sizes, compressors, and worker counts would obscure this question. High database counts and other workloads remain unmeasured limitations in the report, linked to issue #87, rather than extra matrix cells. Task 1.2 covers the unknown baseline cost.

### Gate the prototype on removable stream cost

Store the frozen protocol in a compact reproduction configuration at `reports/stream-cost/shared-invalidation-v1/config.json`. Record its hash in local results. These thresholds are research investment criteria, not product service-level objectives.

For each block, model, and workload, let `C(N)` be MongoDB CPU with N stream-only workers minus its matched N-worker no-stream control, divided by the fixed 60-second application window. Include bounded post-window drain CPU in active totals and report it separately. Estimate removable duplication as `C(8) - C(1)`. Report idle polling and active delivery costs separately, plus active-minus-idle excess as a diagnostic of event-driven work. Neither idle overhead nor native-cache refetch savings substitutes for active stream-only evidence.

There are four predeclared opportunity comparisons: idle and active in sync and asyncio. Proceed when any comparison's basic-bootstrap lower bound exceeds **0.05 CPU seconds per second**, using nominal family error 0.05 and Bonferroni over these four alternatives (`alpha=0.0125` each). A passing comparison requires all six matched blocks for that cell. Retain failed cells among the four alternatives; missing or overlapping evidence cannot pass. If no cell passes, distinguish complete below-threshold results from inconclusive ones and scope deferral to the measured workloads.

Reuse the weighted six-block enumeration in `await_statistics.py`: all `6**6 = 46,656` ordered draws, represented by their 462 multiplicity vectors. Extend that shared helper with signed basic-statistic support while preserving its existing positive log-statistic callers; CPU differences must not be shifted or clamped to fit the log API. For observed statistic `t`, center every resample as `d=t_star-t`; use lower bound `t-q_(1-alpha)(d)` and upper bound `t-q_alpha(d)` with weighted nearest-rank quantiles. Exact enumeration removes Monte Carlo tail noise, not bootstrap approximation or dependence assumptions. Task 1.2 covers the decision implementation.

If the gate is unmet, complete the conditional task group with the recorded skip reason. Still assess the alternatives and continuity model in the final report. If it is met, compare independent-stream and shared-stream research variants on identical receivers and schedules, accounting for coordinator and IPC CPU, private memory, and bytes. Keep native-manager results as a separate reference; stream-count reduction alone cannot establish net savings.

### Decide prototype benefit per group and workload

Freeze the prototype protocol in the same reproduction configuration before baseline sampling: eight subscribers, homogeneous sync, homogeneous asyncio, and mixed four-sync/four-async groups; the same two windows and six counterbalanced paired blocks. Reset both variants between windows. For each group/window, the server statistic is the mean paired independent-minus-shared CPU-rate difference; the application statistic is the shared/independent ratio of total non-MongoDB CPU seconds, counting each worker, coordinator, writer, proxy, and harness process exactly once. Include separately identified drain costs and normalize rates by the same 60-second denominator. Use the exact paired-block basic bounds defined above; a reference rate at or below 1e-6 seconds per second in the observed data or any resample makes a CPU ratio unresolved.

Each possible recommendation is scoped to one of the six group/workload combinations. It requires that workload's server CPU-saving lower bound exceed zero, both workloads' application CPU-ratio upper bounds be at most 1.05, and every active pair/subscriber in that group satisfy the lag checks below. Apply `alpha=0.05/6` to each recommendation because selecting any one of six opportunities is an OR decision; failed combinations remain in that family. Within a recommendation the checks form an intersection-union decision: every component must pass at that alpha, without another adjustment across components, pairs, or subscribers. A false conjunction necessarily contains a false component that must pass. Report intervals as marginal bounds, not a simultaneous confidence band for every measurement. All protocol fault cases must also pass before any positive recommendation.

### Register event-count lag captures

For each native-manager active cell and each prototype active pair/subscriber/variant, reset lag capture after warmup and retain **six windows of 20 contiguous invalidation-producing events**, separated by **16 uncaptured invalidation-producing events**. The captured ordinal ranges are 1–20, 37–56, 73–92, 109–128, 145–164, and 181–200. Every subscriber must receive all 200 scheduled updates; retain 120 lag samples and verify the separation counts independently. Exclude warmup, unrelated namespaces, and readiness messages. The 60-second application window is not the bootstrap unit. The existing bounded capture configuration can represent these counts without changing the observability contract.

For prototype lag inference, enumerate all six-window draws uniformly with their exact multiplicity weights, retaining every event within a selected window. Use weighted percentile intervals matching `bootstrap.py`'s capture-window estimator, extended to exact enumeration through the shared statistics helper. For each active pair/subscriber require both variants' p95 interval upper endpoints, expanded by their pair's clock uncertainty, to be at most 500 ms. For the shared-minus-independent delta, compute each variant's interval at confidence `1-alpha/2`, subtract endpoints (`shared.upper-independent.lower` for the upper bound), and add twice the pair's total clock uncertainty; require the result to be at most 10 ms. This per-variant Bonferroni adjustment is local to constructing one delta bound; it is not a correction over all safety checks. Absolute intervals use confidence `1-alpha`. Both are two-sided percentile intervals, giving conservative upper bounds for the conjunction. Do not pool subscribers or average away a failing pair; missing captures or unresolved bounds prevent that group's recommendation.

Use a common initial server clock offset for each active pair, calibrate every 50 ms (one tenth of the absolute lag ceiling, matching `validate_cadence()`), and reject clock drift or wall/monotonic divergence above 5 ms and any primary change. Record the residual undetected-transient limitation. A 20-event capture spans approximately six seconds and its 16-event separation approximately 4.8 seconds under the paced schedule; these are workload-specific dependence assumptions, not protection against arbitrary correlated delay. Native-manager lag intervals remain descriptive and use nominal confidence 0.95.

Include the capture configuration, a 50 ms application-schedule tolerance, a 10-second drain limit, and 30-second startup/10-second shutdown bounds in the frozen configuration. Collect every scheduled event's lag through that bounded drain rather than censoring events arriving after 60 seconds. These scheduling and lifecycle bounds apply to every phase. Responsiveness thresholds are research criteria rather than product service-level objectives.

Immediate prototyping would produce performance evidence sooner but spend effort before proving an opportunity. Demanding a user workload before any measurement would improve relevance but prevent a bounded initial investigation. The registered gate chooses a conservative local experiment; its external relevance remains an explicit unknown for task 3.1.

### Assess transports; prototype only private same-host IPC

| Model                                         | Benefit                                                       | Cost / limitation                                                           | Unknown and disposition                                                                                          |
| --------------------------------------------- | ------------------------------------------------------------- | --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Independent managers                          | Existing ownership and no extra transport                     | Repeated MongoDB consumers                                                  | Cost measured in task 1.2                                                                                        |
| One local coordinator with bounded IPC queues | No broker dependency; same host can share MongoDB consumption | Fan-out and subscriber recovery remain necessary; local lifecycle coupling  | Net cost and fault handling measured conditionally in task 2.1                                                   |
| Sidecar with socket delivery                  | Can outlive application workers and serve multiple runtimes   | Deployment, authentication, framing, and reconnect responsibilities         | Assess operational fit in task 3.1; no sidecar prototype in this change                                          |
| External pub/sub or durable log               | Can span hosts; durable replay may preserve continuity        | Another service, permissions, delivery guarantees, and retention management | Assess continuity requirements in task 3.1; product validation would require a separate proposal under issue #87 |

Choose standard-library bounded multiprocessing queues for the conditional experiment. Their serialized messages are restricted to trusted children spawned by the harness, with no externally reachable endpoint; this is not a safe transport for untrusted publishers. [Python's multiprocessing documentation](https://docs.python.org/3.14/library/multiprocessing.html#pipes-and-queues) describes their serialization and feeder-thread behavior, which must be included in lifecycle and backlog accounting.

### Model delivery at the cache-core boundary

The prototype owns its `CacheCore` instances and local query/admission driver. It uses the shipped router and generation checks, without replacing a manager's private coordinator or modifying `src/`. An independent-stream research variant uses the same receivers and local read driver as the shared variant, avoiding comparisons between different read implementations.

The coordinator watches the existing projected routing events, carrying a database, coordinator epoch, subscription epoch, and increasing sequence number. Each subscriber has its own bounded event queue (256 messages), a background receiver, and local availability/expiry state. Synchronous receivers use a thread; asyncio receivers offload blocking queue reception. Healthy lookups inspect only local state and time. Cache values never enter the transport.

Use `try_next()` to observe empty batches as well as events; [PyMongo documents](https://pymongo.readthedocs.io/en/4.18.1/api/pymongo/change_stream.html#pymongo.change_stream.ChangeStream.try_next) that it may return no event while updating the resume token. Freshness certificates contain an upstream observation time and the last published sequence, and are emitted only after a successful poll has drained its returned events. Mere coordinator heartbeat activity is not a certificate. Subscribers refresh a three-second local lease only after applying every event through a certificate's sequence; late certificates cannot renew an expired observation.

Initialize unavailable. On join, rejoin, upstream uncertainty, or changed epoch, disable admission/lookup and clear the affected database before accepting a new ordered readiness certificate. Reset queues/subscription epochs on overflow; never drop an event and continue the same healthy subscription. A missing sequence, expired lease, or unexpected epoch makes a subscriber unavailable until re-established. Lease expiry bounds local detection of a silent failure, not MongoDB commit-to-invalidation delay or a per-write catch-up promise. Check expiry during every read/admission decision, including when the receiver is stalled.

Exercise coordinator death, a live coordinator with a stalled watch, paused subscribers and overflow, dropped/reordered/duplicate envelopes, late join/rejoin, epoch changes, history loss, database invalidation, and admission spanning recovery. Certify equivalent local-state behavior for sync, asyncio, and a mixed group. A slow subscriber must not block other queues; it is detached and recovers through the same unavailable/clear path.

Fan-out sends and receiver work remain O(workers × events), and cache occupancy remains proportional to workers' local working sets. The hypothesis is reduced MongoDB stream/polling work, not elimination of per-worker invalidation work. Bounded queues cap retained delivery messages; measure encoded IPC payload sizes separately from transport overhead. Automatic fallback to native managers would restore availability but needs additional stream ownership and switching semantics; it is excluded from this experiment and assessed only in task 3.1. The protocol's correctness and conservative lease's bypass cost remain unknown until task 2.1; they are not current library guarantees.

## Risks / Trade-offs

- Host noise or clock uncertainty can conceal a small benefit → Preserve failed cells and confidence bounds; do not promote an inconclusive comparison.
- A coordinator becomes a shared failure source → Evaluate the delta's failure cases; retained native behavior remains the supported contract.
- Primitive results omit manager integration and deployment costs → Label them explicitly and scope any positive recommendation to further proposal work.
- Container or private-memory metrics may be unavailable → Fail required setup visibly; retain the blocker rather than substituting budgets, parent CPU, or logical bytes.
- The same-host trust boundary exposes identifiers to the coordinator → Document the additional access boundary and required publisher authorization for any future transport.

The canonical output is `docs/development/research/shared-invalidation-feasibility.md`, linked from `docs/development/index.md`. It holds concise measurements, protocol/configuration references, all outcomes, transport assessment, and the recommendation. Raw outputs stay under ignored `benchmark-reports/`; no CI timing gate or supported deployment change is part of this work.
