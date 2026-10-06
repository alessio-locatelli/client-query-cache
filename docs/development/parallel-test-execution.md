# Parallel test execution

Ordinary pytest commands use automatic parallelism with at most four workers. Tests in each file
stay on one worker (`--dist=loadfile`), so they reuse module fixtures such as disposable MongoDB
replica sets and proxies. Workers that need MongoDB own separate session replica sets.

Choose a worker count for the available resources:

For `-n 2`, `-n 8` and `-n 0` below: The default is the configured automatic worker count.
We override it because these examples select a concrete worker budget for available resources
([xdist 3.8.0](https://pytest-xdist.readthedocs.io/en/stable/distribution.html)).

```console
just pytest -- -n 2 tests/core
just pytest -- -n 8 tests/core
just pytest -- -n 0 tests/core
```

Numeric counts have no repository ceiling; `-n 0` runs serially. Automatic and logical CPU selection
are capped at four. Worker restarts retain [xdist's defaults](https://pytest-xdist.readthedocs.io/en/stable/distribution.html).

## Coverage

`just tests_and_coverage` runs the full suite once and combines branch coverage from every worker
with pytest-cov. It uses the existing coverage configuration, isolated coverage workspace,
100% threshold, and strict exclusion checks. Use the same command serially for comparison:

For `PYTEST_ADDOPTS='-n 0'`: The default is no environment-supplied options. We override it
because this comparison must disable automatic workers while keeping the coverage recipe
([pytest 9.1.1 precedence](https://docs.pytest.org/en/stable/how-to/usage.html#specifying-which-tests-to-run)).
For both `CI=true` commands: The default is inherited from the caller, otherwise unset.
We override it because this comparison must use the external benchmark's CI skip policy.

```console
CI=true PYTEST_ADDOPTS='-n 0' just tests_and_coverage
CI=true just tests_and_coverage
```

`CI=true` uses the external MongoDB benchmark's existing skip policy. Ordinary runs keep the same
test selection and conditional skips, including exclusion of the opt-in memory tier and the
specifications submodule. Independent example subprocesses and installed wheels are not
instrumented by this coverage command.

## Diagnostics

The controller writes `pytest.log`; workers write `pytest-gw0.log`, `pytest-gw1.log`, and so on.
A custom `--log-file=diagnostics/run.log` produces `diagnostics/run-gw0.log` for worker zero.
Serial runs retain the selected path, and `/dev/null` disables file output in either mode.
Choose separate destinations for simultaneous pytest invocations. The database-backed CI job
retains controller and worker logs on failure for seven days.

## Serial debugging and measurements

Run interactive debugging and live output serially because distributed workers do not support
interactive standard input/output:

For serial-debugging `-n 0`: The default is the configured automatic worker count. We override it
because serial execution helps isolate distribution failures. For `--pdb`: The default is false.
We override it because this example opens the debugger at the failure site. For `-s`, the default
is configured fd capture. We override it because interactive debugging needs live input/output
([pytest 9.1.1](https://docs.pytest.org/en/stable/reference/reference.html)).

```console
just pytest -- -n 0 --pdb <node-id>
just pytest -- -n 0 -s <node-id>
```

`just test-memory` and the benchmark tox environment explicitly select serial execution.
Run the [external MongoDB benchmark](../../CONTRIBUTING.md#real-server-benchmark) separately for
isolated timing, retaining the recipe's optional environment-file loading:

For `-n 0`: The default is the configured automatic worker count. We override it because latency
measurements must run without competing worker processes.

```console
just pytest -- -n 0 tests/benchmark/real_server/test_cache_benefit.py
```

That benchmark remains part of ordinary full-suite selection when configured, where it competes
with other workers. Full-suite timings are not isolated evidence of the library's performance.
