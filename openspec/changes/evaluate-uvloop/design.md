# Design

## Context

See `proposal.md` for motivation and affected surfaces. The package supports CPython >=3.14. Its benchmark dependency group already includes psutil and testcontainers; pytest-asyncio is declared at >=1.4.1. The installed plugin implements the requested factory hook, but its exact locked version and uvloop's supported build must be recorded during execution.

`benchmarks/public_shared_cache.py` runs spawned workers with `asyncio.run(_measure_async(window))`. It already selects async models, direct/independent/shared paths, hot/cold workloads, read methods, worker count, sample count and repetitions. It validates results and cache trajectories and records latency percentiles, throughput, worker/owner/harness CPU and separate MongoDB CPU. Its default measurements enable telemetry; the production-default comparison must explicitly use `--disable-telemetry`.

`pytest.ini` uses asyncio auto mode, function-scoped fixture loops and bounded xdist execution. `tests/conftest.py` starts MongoDB before the ordinary fixture phases through `pytest_runtest_protocol`; pytest phase durations alone therefore omit meaningful startup overhead. `tests/asynchronous/conftest.py` owns async clients and process-local managers. `tests/shared_cache/test_public.py` covers shared attachment, reads, invalidation, reconnection and cancellation with real processes.

## Goals / Non-Goals

**Goals:** The delta specs own acceptance criteria. This design specifies a small measurement protocol and the seams for conditional integration.

**Non-Goals:** No runtime API, dependency extra, automatic loop selection, Rust change, alternative loop implementation, historical benchmark requalification or new benchmark framework. The two alternatives excluded by the task will not be investigated.

## Decisions

### D1. Add only enough loop selection to reuse the public harness

Use a named asynchronous-loop selector at the harness boundary and carry its value through the spawn-safe worker configuration. Resolve the uvloop factory once per worker before `asyncio.run`, outside measured operation loops. Record the selected loop and its version in output. Preserve the existing standard-loop invocation. Reject explicit unavailable selections visibly before expensive setup.

For initial evaluation, load uvloop through an ephemeral uv environment addition. Retain a locked development-only dependency only if ongoing integration qualifies. This avoids imposing an unproven dependency on ordinary development. A separate microbenchmark could isolate scheduler cost but would omit the cache, PyMongo and shared-owner costs that matter here. It is therefore disproportionate; no further investigation of a separate framework is necessary. The unresolved dependency/build compatibility is checked by task 1.1.

Expected cost boundaries:

| Path           | Work relevant to the comparison                                                                                            |
| -------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Hot hit        | Key handling and BSON decode; data size contributes CPU and allocation costs; background stream scheduling remains active. |
| Cold miss      | MongoDB round trip and decode plus admission and background work; shared mode adds owner activity.                         |
| Worker startup | Imports, loop/client/manager creation and warmup; excluded from operation timing, retained in process measurements.        |
| Test process   | Collection, container startup, fixtures, database commands, assertions and cleanup; measured in total wall time.           |

These are cost expectations, not measured bottleneck claims. No per-read loop lookup or resource construction is introduced.

### D2. Freeze a bounded matched protocol before candidate timing

Use the same checkout, installed package/native artifact, interpreter, dependencies, MongoDB image/resource limits, workload data, seed, telemetry, validation and instrumentation for both loops. Record host and dependency versions and exact commands. Run without competing builds or tests. Pre-pull the database image and synchronize dependencies before timing; retain normal replica-set startup inside end-to-end measurements.

Initial operation matrix: async `identity`, `direct independent shared` paths, `hot cold` workloads, four workers, 2,000 samples per worker, `--validate --disable-telemetry`. Each worker awaits one foreground read at a time; four processes provide four separate loops rather than concurrent foreground requests on one loop. This matrix supports only the scope in the benchmark delta's sequential-worker scenario. Adding task fan-out would require defining request scheduling, admission pressure and latency ownership; it could establish broader applicability but adds a new workload before any benefit is known. Choose the existing sequential workload for this evaluation; no concurrent-workload follow-up is required. Add a second read shape with `--method find_one` only as a descriptive guardrail if identity results establish a benefit or identify a shape-specific question; it cannot independently qualify adoption.

First perform an untimed compatibility/validation smoke. Use baseline-only sizing to increase samples only if timed windows cannot resolve CPU or timing variation. Freeze sizes before uvloop timing. Then run twelve independent paired blocks with one harness repetition per invocation, alternating AB/BA, where A is asyncio and B is uvloop. Recreate and seed equivalent disposable state for each invocation. Keep each invocation's complete path matrix and do not pool requests across runs as independent evidence.

For each default-path cell report per-run median/P95/P99 latency and throughput. The latency metric used for adoption is the median; throughput and tails remain companion checks. Apply D2a to the four independent/shared hot/cold cells; direct-driver cells are descriptive controls.

The existing harness calls `await_admissions()` for validated shared cold windows only when telemetry is enabled; its later follow-up reads occur after owner CPU is sampled. Consequently, the default-path matrix cannot supply complete owner/group CPU accounting. Label those CPU fields incomplete and exclude them from efficiency and regression decisions. Run a separate matched resource pass for all four manager cells with telemetry enabled and `--validate --diagnostics`, regardless of latency outcomes. Use the same frozen sizes, twelve-pair schedule and loop comparison. The existing drain must verify expected owner processing and residency before the final owner CPU checkpoint; subsequent `reconcile_admissions()` checks the captured worker counts and invalidates the window on disagreement. Retain foreground latency, drain duration, worker CPU, owner CPU, group CPU per completed read and separate server CPU, and expose their existing measurement scopes rather than treating them as one common interval. Group CPU per completed read is the resource metric used for adoption under D2a; other resource measures are descriptive checks. A CPU-only benefit can justify use in that telemetry-enabled benchmark configuration, without a default-path CPU recommendation. Any reproducible CPU regression requires investigation; unresolved accounting or adverse costs prevent adopting the affected workload.

This split uses an existing completion barrier. A telemetry-independent barrier could measure default-path CPU directly, but none exists in the current harness; creating a new runtime observation mechanism solely for this experiment would be disproportionate and violate production-scope constraints. No such barrier is planned. Task 1.2 verifies the split and task 2.1 records its evidence and limits.

Sequential batches with all asyncio runs first are easier to run but confound loop choice with host drift. Interleaving costs little and is preferred. A much larger exhaustive matrix would improve generality at disproportionate expense. Task 1.2 resolves sizing, task 2.1 resolves measured uncertainty; no unbounded expansion is planned.

### D2a. Estimate paired effect magnitudes with bounded uncertainty

For each primary metric calculate one log ratio per independent pair, `log(uvloop / asyncio)`. Estimate its mean and a Student-t interval using the paired differences and eleven degrees of freedom, then exponentiate to report the geometric mean ratio and interval. Use two-sided 99.375% intervals for each operation comparison: four default-path latency estimates and four instrumented group-CPU estimates form one Bonferroni family with 95% coverage. Use a two-sided 95% interval for D3's single primary metric. The paired-difference method is described in the [NIST handbook](https://www.itl.nist.gov/div898/handbook/prc/section3/prc312.htm). Lower latency, CPU cost or duration favors uvloop.

Twelve pairs provide six observations per order group and an estimate of effect dispersion while keeping this a finite engineering experiment; they do not guarantee resolution of any given effect. A qualifying interval must lie below ratio 1, both order groups must have an improving mean, and the direction of the overall mean must survive leaving out each pair in turn. Report individual ratios, median and range as well as the estimate. Occasional slower observations are retained and may coexist with a qualifying effect; there is no required win count or minimum percentage. Inspect paired log effects for severe skew, isolated dominant observations and time trends: if these undermine the interval's approximate-normality or independence assumptions, report the result as inconclusive rather than deleting samples or silently changing estimators.

The former sign-only method has weak power at a small sample budget and discards effect magnitude. Bootstrap intervals avoid a distributional assumption but are unstable at very small run counts and require additional resampling choices. Choose the transparent paired interval with the stated diagnostics; task 2.1 determines whether its assumptions and uncertainty permit a conclusion. Stop at twelve pairs without optional extensions for significance. Changed sizing or analysis requires a recorded reason and a fresh affected comparison. Investigate every reproducible slowdown, and discuss material adverse trade-offs before acceptance.

### D3. Evaluate tests independently using existing cases

Implement a scoped `pytest_asyncio_loop_factories(config, item)` hook, initially in a temporary pytest plugin under `/tmp/agents/`. Return only the selected factory during timing, so both invocations run the same cases once. Verify factory identity and nonempty collection parity before measurement. The current hook parametrizes every returned factory: returning both globally would duplicate all async tests.

Use `tests/asynchronous/test_manager.py`, `tests/asynchronous/test_streams_integration.py` and these shared-public cases as the initial timing subset:

- `test_public_shared_reads_invalidate_and_reconnect`
- `test_public_find_bypasses_and_close_preserves_client`
- `test_async_close_defers_repeated_cancellation`

The first two shared-public tests use a `manager` fixture parametrized over sync and async managers. Select only their async-manager variants by collected node ID, retaining other fixture parametrization, and verify that the sync variants are absent from the timing selection. The cancellation case already uses an async attachment. These are complete pytest-run measurements, not isolated cache-operation measurements; D2 owns the latter.

Run twelve AB/BA paired fresh-process invocations with `just pytest -- -n 0`, identical selection and logging, no coverage or profiler, and `--durations=0`. Measure external monotonic elapsed time around pytest; record collection/startup overhead and setup/call/teardown separately, treating their residual as overhead rather than attributing it to the loop. Use D2a with total process wall time as the single primary metric; phase timings are descriptive. Serial runs isolate the effect; if a normal-run speed claim or default change is proposed, repeat the qualifying subset under the configured xdist execution and require confirmation there.

If retained, move only the necessary hook/selection into existing conftest infrastructure. Ordinary collection returns asyncio only except for explicitly designated dual-loop compatibility cases. Faster uvloop-only invocations may be offered for the qualifying subset, while the full standard-loop suite remains the compatibility authority. Compare retained harness and hook changes against `main` under equivalent standard-loop conditions to detect instrumentation or collection overhead; measure existing tests separately from added compatibility cases. A global uvloop default is unnecessary for this bounded optimization; duplicating the full suite increases test cost and is excluded by the test delta. Exact speed benefit is unknown until task 2.2; task 3.1 selects retained scope from that evidence.

Hook documentation: <https://pytest-asyncio.readthedocs.io/en/stable/how-to-guides/uvloop.html> and <https://pytest-asyncio.readthedocs.io/en/stable/how-to-guides/custom_loop_factory.html>. Policies and the deprecated `event_loop_policy` fixture are not used.

### D4. Keep decision evidence proportional

The PR description is the canonical measurement summary: commands, environment, workload sizes and rationale, paired results/variation, overhead accounting, compatibility outcomes and separate benchmark/test/documentation decisions. Use `/tmp/agents/` for raw data and analysis scripts. A permanent experimental report adds little maintenance value here and is not planned. If no adoption qualifies, remove experimental loop selectors and dependencies; retain only verified, useful compatibility guidance. Do not create a runtime shim for a dependency defect. Necessary deferred work needs a GitHub issue, and an upstream defect additionally needs the documented tracking URL required by AGENTS.md. Task 3.2 resolves documentation placement and follow-up ownership.

## Risks / Trade-offs

- Host noise or CPU clock resolution can obscure a small benefit → use D2's sizing and uncertainty protocol.
- Cache hits may do little scheduler work, while database startup dominates tests → report the distinct scopes in D2 and D3 without extrapolating one into the other.
- Fixtures or cancellation may behave differently → preserve visible failures and investigate before integration, as required by the test delta.
- An unavailable uvloop build on a supported Python line can block evaluation → report the limitation, preserve standard coverage and avoid silently claiming support.

## Migration Plan

There is no production migration. Retained changes use existing development commands. Rollback consists of removing the optional development integration while keeping the standard-loop suite and baseline commands. Adoption is resolved in task 3.1; no result is assumed during planning.
