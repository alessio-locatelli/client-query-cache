# Design

## Context

The shared worker cache harness in `benchmarks/stream_cost/shared_cache/` already runs open-loop worker groups against a disposable single-member replica set. It records the following:

- request latency from each request's scheduled issue time;
- completion and overload;
- per-owner CPU and group PSS;
- MongoDB container CPU and memory;
- command-observed stream openings;
- manager hit, miss and bypass counters;
- captured invalidation lag with a calibrated clock offset.

It also already implements `direct` and `independent` paths, `active` windows that issue writes from a writer pool, baseline-only calibration and a `--baselines-only` mode. Several values are fixed in code rather than in the registration:

- the default path tuple;
- the phase list;
- round-robin key partitioning across workers (`Assignment.ordinals`);
- a fixed `active.updates` count per window that targets the whole catalogue;
- shared-versus-baseline gate criteria in `analysis.py`.

The v4 registration in `reports/shared-worker-cache/v4/` is frozen, and its research report cites module commands at pinned revisions.

## Goals / Non-Goals

**Goals:**

- Drive the existing harness from one new registration without changing what the v4 registration plans or analyses.
- Produce a descriptive comparison between direct reads and independent managers, not a promotion decision.

**Non-Goals:**

- Fault, failover and restart timing, which belong to `benchmark-worker-fault-recovery`.
- Synchronous workers, multiple databases, skewed key popularity, document-size sensitivity and capacity staircases.
- Any change to the library's runtime behaviour.

## Decisions

### Harness reuse

Generalize the shared-cache harness so that the registration declares the paths, phases, key assignment, hot set and write mix. The new registration lives at `reports/concurrent-worker-workload/v1/` and is selected with the existing `--config` option.

| Alternative                                             | Pros                                                                                       | Cons                                                                                                         |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------ |
| Generalize `shared_cache/` in place (chosen)            | Reuses tested collectors, calibration, resume and analysis; one code path for both studies | Package name no longer describes every use                                                                   |
| New package that copies the window and worker code      | Clean name                                                                                 | Duplicates about 2,000 lines of tested measurement code                                                      |
| Extend `multiprocess_run.py` from the stream-cost study | Already multi-process                                                                      | Measures stream cost, not scheduled request latency, PSS or hit counters                                     |
| Rename the package to a neutral name                    | Accurate name                                                                              | Breaks the module commands in the shared-cache research report and registration on `main`, for cosmetic gain |

Unknowns: none that need a prototype. The v4 equivalence check in task 1.1 guards against regressions. Conclusion: no further research is needed.

### Workload registration

These are the provisional values that task 2.1 writes into the draft configuration. Only calibration may change the rate and duration before freezing.

| Parameter          | Value                                                                               | Reason                                                                                                              |
| ------------------ | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Data               | `primary` profile: 16,384 documents, 4 KiB payload, seed 197                        | Reuses measured encoded sizes from v4                                                                               |
| Hot set            | 1,024 keys, about 4.3 MiB encoded                                                   | Fits each manager's 96 MiB budget, so eviction can't confound invalidation                                          |
| Read               | `find_one({"_id": key})`, primary, majority read concern                            | Same as v4, so direct and cached work stay equivalent                                                               |
| Write              | `$inc revision` on a seeded uniform draw from the hot set                           | Every write invalidates a key that workers read                                                                     |
| Read and write mix | 20 reads per write, as a share of the offered rate                                  | Writes are frequent enough that invalidation visibly competes with hits, without becoming a write-dominant workload |
| Workers            | 1 and 4, asyncio, per-worker concurrency 4                                          | Matches the issue's comparison and the FastAPI deployment shape                                                     |
| Window             | 60 s minimum, extended by the registered sample-floor rule                          | Carries the v4 floor of 10,000 latency samples per run                                                              |
| Blocks             | 12, with path order alternating by block parity                                     | Paired-block estimates; each order runs six times                                                                   |
| Priming            | Each worker reads the whole hot set before the window, including on the direct path | Both paths start warm; priming cost is recorded separately                                                          |

Alternatives:

- **Synchronous and asyncio models.** Doubles the matrix. v4 screening showed that both models ranked paths the same way. Excluded.
- **Skewed (Zipf) popularity.** No measured real-world exponent exists for this library's users, so the choice would be arbitrary. A uniform hot set is the simpler shape to describe and reproduce. Excluded.
- **Eight workers.** v4 showed eight-worker cells close to saturating the 8-CPU host, which confounds results. Excluded.
- **100 reads per write.** At about 1,300 reads/s, each key would be written roughly every 80 s and nearly every read would hit, so the workload wouldn't exercise simultaneous writes. Rejected.

Unknown: the frozen rate, which depends on how many reads one direct asyncio worker can sustain. Task 2.2 settles it. No other research is needed.

### Shared key assignment

The registration adds `key_assignment`, either `partitioned` (v4's behaviour and its default) or `shared`. Under `shared`, each worker walks its own seeded permutation of the whole hot set. The aggregate offered rate and the global schedule stay unchanged, and only the key chosen for each request ordinal changes.

Partitioning would leave each of four workers reading only a quarter of the keys. That overstates hit rates compared with a load-balanced deployment, in which each worker receives every key. No alternative keeps both the v4 plan and realistic routing, so the option is required. No further research is needed.

### Write mix

The registration adds `active.reads_per_write` and `active.write_keys` (`hot`). The window derives `updates = floor(rate × window / reads_per_write)`, with targets drawn from a seeded permutation of the hot set. v4 keeps `active.updates`, and the two are mutually exclusive in configuration validation.

At about 1,300 reads/s, this gives about 65 writes/s. The four existing writer threads issued v4's 3.3 writes/s within 3 ms of schedule. Whether they keep within the 250 ms dispatch tolerance at 65 writes/s is unknown. Task 2.2's validation enforces the tolerance. If validation fails, the response is to raise the writer pool size in a new registration version, not to relax the tolerance.

### Descriptive analysis

`analysis.py` gains a mode that reads its comparison pairs (`independent` over `direct`) and measures from the registration, instead of the fixed `CRITERIA` gate. For each worker count, it reports the following:

- paired-block ratio and delta point estimates, with block-bootstrap 95% percentile intervals (the existing `bootstrap` code, seed 197);
- throughput and request P50, P95 and P99;
- MongoDB CPU, worker CPU per completed request and harness CPU, each separately;
- steady and peak group PSS;
- hit, miss and per-reason bypass counts;
- observed stream openings;
- lag P50 and P95 with offset and uncertainty.

No promotion gate exists, because nothing ships from this result.

A gated design was considered and rejected. It would need thresholds that no decision depends on, and a "pass" could be misread as a performance guarantee. No further research is needed.

### Bypass and outcome accounting

The report shows manager snapshot deltas as counts. A single read can record more than one bypass reason, so the report never divides bypass counts by requests. Hit and miss counts appear next to completed requests only for orientation. This applies the spec requirement and involves no alternatives.

### No shared Redis comparison

A shared Redis cache would match this library's freshness only if something invalidated Redis entries on every MongoDB write. That could be either:

- write-path deletes in the application, which miss writes made by other services; or
- a change-stream consumer that this project would have to build and operate.

Either way, the comparison would measure that invalidator and Redis's network round trip, not a deployment choice available to users of this library. A TTL-only Redis setup offers different freshness, so it isn't equivalent work.

| Alternative                                    | Pros                                                                          | Cons                                                                    | Unknowns                     |
| ---------------------------------------------- | ----------------------------------------------------------------------------- | ----------------------------------------------------------------------- | ---------------------------- |
| Exclude (chosen)                               | Keeps the comparison to work that users can actually deploy with this library | No external reference point                                             | None                         |
| Redis with a change-stream invalidator sidecar | Equivalent freshness                                                          | Builds and benchmarks a second product; adds a container and dependency | Sidecar lag and its CPU cost |
| Redis with TTL                                 | Easy to build                                                                 | Not equivalent freshness; the comparison would mislead                  | None                         |

Shared invalidation stays under [#87](https://github.com/alessio-locatelli/client-query-cache/issues/87). The research report states this exclusion and its reason. No further research is needed.

### Report placement

The full evidence goes in `docs/development/research/concurrent-worker-workload.md`, linked from `docs/development/index.md`. The registration companion holds the protocol. Public guides carry only the figures that help a reader decide:

- `docs/user/benchmarks/index.md`: a short "Multiple workers with concurrent writes" section;
- `docs/user/operations/deployment.md`: the multi-worker section, updated only where measured figures refine its guidance.

A separate public results page was rejected, because it would repeat the development report and compete with the guide's existing "is caching a good fit" checklist. No further research is needed.

### Catalogue multi-worker launch

The example gains a `--serve` mode with `--workers N` and `--port P` options. This mode:

- calls `uvicorn.run("fastapi_catalogue_example:create_served_app", factory=True, workers=N, app_dir=<example directory>)`;
- reads the content-cache flag from an environment variable, because Uvicorn's spawned workers construct the app themselves;
- has each lifespan log one line when its manager starts and one when it closes the manager before the client, both carrying the worker's PID.

`uvicorn` joins the script's inline dependencies. Requests still need the application's trusted authentication, so the verification accepts a `401` as proof that a worker served the request.

| Alternative                                   | Pros                                                         | Cons                                                  | Unknowns                                                                                                           |
| --------------------------------------------- | ------------------------------------------------------------ | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Uvicorn `--workers` from `--serve` (chosen)   | One documented `uv run` command; FastAPI's documented server | Adds one inline dependency                            | Whether Uvicorn's spawned workers can import the script module through `app_dir` under `uv run`; task 4.1 verifies |
| Gunicorn with Uvicorn workers                 | Common in production                                         | Two extra dependencies; POSIX only                    | None                                                                                                               |
| Documented command only, without verification | No code                                                      | Violates continuous verification; the command can rot | None                                                                                                               |

If task 4.1 finds that `app_dir` import fails, the fallback is a sibling module that `--serve` passes to Uvicorn. That changes the file layout but not the spec.

## Risks / Trade-offs

- [The single host and single-member replica set understate network latency and overstate the CPU that direct reads compete for] → The report and public figures state the topology. The illustrative chart remains the reference for remote latency.
- [Four workers, the harness and two MongoDB CPUs share eight logical CPUs] → Calibration keeps both paths below saturation. CPU is reported per owner, so contention stays visible.
- [Write dispatch at about 65 writes/s may exceed the tolerance] → See [Write mix](#write-mix).
- [Generalizing the harness could change v4 plans] → Task 1.1's equivalence test pins the v4 planned cells and analysis output.
