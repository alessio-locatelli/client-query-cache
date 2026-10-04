# Design

## Context

See [proposal.md](proposal.md) for motivation. `pytest.ini` currently selects `tests/`, ignores the specifications submodule, excludes memory tests, and sends all file logs to `pytest.log`. `just tests_and_coverage` runs `coverage run -m pytest` once, then reports coverage and checks exclusions with `strict-no-cover`. That controller-only invocation cannot be carried forward unchanged when tests execute in separate workers.

`tests/conftest.py::mongodb_uri` owns a session-scoped Testcontainers replica set with a dynamically exposed port and `ExitStack` cleanup. Session fixtures execute independently in xdist workers. `cached_database_name` generates a UUID for each test. The synchronous and asynchronous clients and managers are function-scoped. The end-to-end wheel/environment fixture uses `tmp_path_factory`; it does not build into shared `dist/`.

Two integration files have expensive module fixtures: `test_await_run_integration.py` owns a replica set, and `test_compression_matrix_runner_integration.py` owns a replica set and proxy. Other topology integration tests create their own disposable runtimes, sometimes in addition to a worker's session replica set. Proxy tests bind dynamically allocated ports. Real-server worker tests use disposable MongoDB, while the optional external benchmark uses its own uniquely named collection. The examples execute subprocesses with their fixture's MongoDB URI.

The existing full suite includes the optional real-server benchmark when configured. This plan preserves that selection. Planning has not executed tests, contacted external MongoDB, or measured speedup. Existing runtime and benchmark semantics are outside this change's ownership.

## Goals / Non-Goals

**Goals:** Establish a speedup before adopting parallel defaults, then retain test selection, branch-coverage enforcement, disposable topology ownership, and useful failure diagnostics.

**Non-Goals:** A shared MongoDB server, a custom scheduler, forced test ordering, test retries, remote workers, new performance thresholds for library code, or memory-tier recalibration.

## Decisions

### 1. Trial parallel execution before changing defaults

Use the [trial command in tasks.md](tasks.md#1-cli-trial-before-repository-changes), which preserves the existing container-runtime bridge and optional environment-file loading while adding xdist ephemerally with `uv run --with`. Compare `-n 0`, `-n 2 --dist=loadfile`, and `-n 4 --dist=loadfile` with the same representative unit and database-backed paths. Use `/dev/null` as the log destination for all trial modes to avoid the known shared-log conflict before log routing exists. Keep `CI=true` in every mode so optional external-service tests retain their existing skip behavior.

Run each mode three times in alternating order on the same host with the configured image already available. Record elapsed times, test/skip counts, slowest tests from `--durations=10`, and observed worker/container resource use. Include fixture startup in wall time. If the trial fails, exposes isolation conflicts, or provides no consistent speedup, stop before the supporting changes and record the result. Resolve only defects necessary for this change; the trial does not authorize unrelated test refactoring.

### 2. Bound automatic workers without capping explicit requests

After a successful trial, add `pytest-xdist[psutil]>=3.8.0` and `pytest-cov>=7.1.0` to the development group and regenerate `uv.lock`. Use this default in `pytest.ini`, alongside the existing ignore and marker selection:

```text
-n auto --dist=loadfile
```

Bound the result of the documented `pytest_xdist_auto_num_workers` hook to at most four using a small hook wrapper in `tests/conftest.py`. Delegate CPU detection to xdist, then return the smaller of its result and the selected automatic limit. This also bounds `-n logical` while leaving explicit numeric requests untouched. Use the successful trial to choose a lower automatic limit if two workers perform better than four.

The [documented auto-worker hook](https://pytest-xdist.readthedocs.io/en/stable/distribution.html) and [pytest hook wrappers](https://docs.pytest.org/en/stable/how-to/writing_hook_functions.html#hook-wrappers-executing-around-other-hooks) support this narrow customization without duplicating CPU detection or changing parsed options. Do not put `--maxprocesses` in repository defaults: current xdist applies it to numeric requests too, while its help describes automatic modes. `-n 2`, `-n 8`, and `-n 0` therefore mean two workers, eight workers, and serial execution. Explicit numeric resource use remains the contributor's responsibility.

Leave worker restart behavior at xdist's default. Its [acceptance tests](https://github.com/pytest-dev/pytest-xdist/blob/v3.8.0/testing/acceptance_test.py) verify that the crashed test fails and a replacement worker executes remaining tests. There is no demonstrated project-specific reason to stop the session at the first crash. Existing timeouts remain unchanged.

### 3. Schedule whole files and retain worker-local MongoDB

The [distribution modes](https://pytest-xdist.readthedocs.io/en/stable/distribution.html) provide these choices:

| Mode        | Suitability for this suite                                                                                                                                                                                   |
| ----------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `loadscope` | Groups functions by module but methods by class, so multiple classes can duplicate module fixtures across workers.                                                                                           |
| `loadfile`  | Keeps the entire file together, including all parametrizations and future test classes; matches current module fixture ownership.                                                                            |
| `loadgroup` | Useful when tests across files share a mutable external resource; no such ownership requirement was found that needs cross-file scheduling here. Ungrouped tests otherwise use fine-grained load scheduling. |

Choose `loadfile` without group markers. Retain the existing lazy session replica set per worker needing `mongodb_uri`. Separate containers isolate fixed collection names between workers, and UUID namespaces isolate ordinary tests on each worker. Module-owned replica sets and proxies remain together on one worker. Confirm setup and cleanup with representative two-worker commands and runtime observations; do not add permanent tests of fixtures or a coordination harness.

Grouping does not impose a global execution order or make benchmark timing exclusive of other workers. Preserve deterministic collection; fix any observed unordered parametrization at its source. Do not add speculative collection guards.

Retain xdist's default capture. `--maxschedchunk` tunes `load`, not this whole-file scheduling policy; `--no-loadscope-reorder` targets `loadscope`. Neither belongs in these defaults. Do not introduce `--dist=each`, which duplicates test execution, or remote-worker options.

### 4. Route each worker's log before logging is initialized

Use a small pytest configuration hook in `tests/conftest.py` before pytest's logging plugin opens its file. Derive worker identity from xdist's worker configuration. Keep the controller destination unchanged and suffix each worker destination: `pytest.log` becomes `pytest-gw0.log`, `pytest-gw1.log`, and so on. A custom `diagnostics/run.log` becomes `diagnostics/run-gw0.log`. Preserve disabled output such as `/dev/null`; serial runs keep their selected path.

Do not reconfigure application logging independently or concatenate worker files during execution. Update the existing CI failure-artifact path to include `pytest.log` and `pytest-gw*.log`, with its current retention and missing-file behavior. The existing `*.log` ignore already keeps these outputs untracked. Logs from separate simultaneous pytest invocations are not isolated by this suffix; contributors needing that must choose separate destinations.

Verify routing by running existing tests with two workers and inspecting the produced files, including a custom destination and serial `/dev/null` run. Do not commit tests of the `conftest.py` hook.

### 5. Let pytest-cov aggregate worker coverage

Replace the recipe's `coverage run -m pytest` with `pytest --cov --cov-config=.coveragerc --cov-report=` in the same isolated `COVERAGE_FILE` workspace. Bare `--cov` preserves the configuration's source selection instead of imposing an unrelated CLI source filter. Disable pytest-cov's terminal report because the existing `coverage report` remains the single report and threshold gate. Retain `.coveragerc`, covdefaults, the prohibited-exclusion check, and `strict-no-cover` without weakening them.

[Pytest-cov supports combined coverage from distributed workers](https://pytest-cov.readthedocs.io/en/latest/xdist.html). Use that integration rather than manual worker coverage startup or combination scripts. Do not enable generic subprocess coverage as part of this change: this migration concerns pytest workers, not instrumenting independent example environments or installed wheels. Verify both serial and parallel runs measure the same production modules and branches and leave exclusion enforcement active.

### 6. Keep measurement and interactive paths serial

Pass `-n 0` explicitly in `just test-memory` and `[testenv:benchmark]`. Keep ordinary unit, integration, end-to-end, and coverage commands on the shared defaults. Document `just pytest -- -n 0 --pdb <node-id>` and `just pytest -- -n 0 -s <node-id>` because [worker standard I/O does not support interactive debugging or live uncaptured output](https://pytest-xdist.readthedocs.io/en/stable/known-limitations.html).

Update the standalone real-server benchmark example to include `-n 0`, retaining its environment-loading behavior. Preserve that benchmark's conditional presence in ordinary full runs, but say explicitly that those runs contend with other workers and do not supply isolated performance evidence. Do not execute it during this change's comparisons: set `CI=true` for both serial and parallel measurement runs, which uses its existing skip policy rather than modifying test selection or reading credentials. Standalone benchmark runner processes and the CI performance guard already run outside pytest distribution; they need no xdist settings.

### 7. Confirm the result with the final coverage command

After the successful trial and supporting changes, compare the final full-suite coverage command serially and at the selected parallel default. Use three fresh pytest processes per mode with identical dependencies, selection, and external-benchmark skips, alternate mode order, and report medians, ranges, test/skip counts, and comparable coverage. Include fixture startup and normal logging in wall time. Observe process-tree memory separately from container memory; one process's peak RSS does not describe total worker cost.

Collection work and Python interpreter memory scale with worker count. The shared fixture creates at most one replica set per database-using worker, but independently owned topology fixtures can raise the concurrent container total above that count. File scheduling reduces repeated module setup but creates a longest-file lower bound on elapsed time. Repeated collection, imports, container startup, property-based tests, and the longest integration files are suspected bottlenecks until measured.

Record the initial trial and final comparison with reproduction commands in `docs/development/parallel-test-execution.md`, including tool versions and host resources. Keep raw output untracked. Record timings, slow-test profiling, and resource observations in the implementation commit body. Accept a parallel default only when the final command improves median full-suite elapsed time without conflicts, missing coverage, or resource exhaustion.

## Risks / Trade-offs

- More MongoDB instances and full collection in every worker → Bound automatic counts based on the trial and observe process-tree plus container resources; contributors can explicitly select a different count.
- One long test file limits balancing → Record its duration and accept file scheduling's safety trade-off; splitting tests is outside this proposal unless measurements establish a necessary change.
- Timing-sensitive integration workloads can fail under contention → Compare repeated runs at two and four workers without relaxing correctness assertions; lower the default if necessary.
- Coverage integration may alter how strict exclusion tooling sees data → Keep the shared coverage workspace and compare serial/parallel reports and exclusion-tool results before accepting the migration.
- Optional external benchmark timings contend with other tests → Preserve selection, document the limitation, and use its serial standalone command for measurements.

## Migration Plan

Trial xdist from the CLI first. If measurements support adoption, update dependencies, defaults, hooks, coverage, serial tiers, and diagnostics together, with contributor guidance. `-n 0` is the immediate operational escape hatch; rollback restores serial configuration and the coverage invocation.

## Observed execution blocker

The first final four-worker coverage run exposed a pre-existing wall-clock dependency in
`generate_seeded_documents`: Faker's default date-time upper bound moves between generations,
so identical seeds can produce different timestamps. Use a fixed UTC date boundary for this
benchmark input while retaining naive, millisecond-precision BSON timestamps. This corrects the
observed deterministic-input defect without weakening assertions or changing test selection.
Repeat the final comparisons after the correction; the failed attempt is not accepted evidence.
