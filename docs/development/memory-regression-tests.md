# Memory regression tests

Run the synthetic cache-churn tier on Linux:

```console
just test-memory
```

The command synchronizes the locked development and `memory` dependency groups and profiles exactly
two cases. It requires no MongoDB or container runtime. See the official
[Memray documentation](https://bloomberg.github.io/memray/) for supported platforms. Missing profiling
support, explicit selection without profiling, and an empty selection fail visibly.

Ordinary unit, integration, end-to-end, coverage, and latency benchmark commands exclude these tests
and do not enable profiling. Explicit marker selections override pytest's default `not memory`
expression, so custom ordinary commands should retain that exclusion.
Ordinary coverage also omits `tests/memory/`, whose bodies remain unexecuted in that tier; production
coverage retains the configured 100% threshold.

## Workload and measurement boundary

Each case keeps one core alive for eight cycles of 1,024 fresh 64 KiB payload admissions, alternating
two namespaces under a shared 4 MiB BSON budget with a 128 KiB maximum entry size. One case admits
identity entries with aliases; the other admits namespace entries. Each admission must succeed and
immediately hit. Every sixteenth admission triggers a write, a miss, and readmission followed by a
hit. Checkpoints every 128 admissions verify budget, eviction, resident entry indexes, identity
references, and alias ownership. Clearing both namespaces at each cycle boundary must empty their
entries and metadata. Closing the core must leave zero entry usage; fixture teardown also closes it
after a failure.

The seeded synthetic payload is generated before profiling. Short-lived helpers release documents,
decoded hits, and admission captures, so the harness keeps no growing workload history. Ordinary
writes invalidate generations but can leave stale entries resident; only clearing and closing are
required to reclaim all entries.

[pytest-memray](https://pytest-memray.readthedocs.io/en/latest/usage.html) tracks peak live allocations
in the test body, across all threads, with Python allocator tracing enabled. Fixtures and imports lie
outside this boundary. The command disables stdio capture, raises both logging thresholds to CRITICAL,
and sends file logging to `/dev/null` to avoid retaining debug history. Pytest's logging plugin stays
enabled because `pytest.ini` contains strict logging configuration.

The ceiling measures neither process RSS nor cumulative allocation volume. This finite workload
does not prove cursor, thread, asyncio-task, or telemetry cleanup, and small leaks can remain below
the ceiling. Structural checks complement the allocation limit.

## Command options

The calibration command below uses these options. Defaults include the inherited
`pytest.ini` values; the recipe explains its own options beside the command.

- `--trace-python-allocators`: The default is false. We override it because the
  allocation ceiling must include Python allocator activity, not only native allocations.
- `--capture=no`: The default is fd capture. We override it because retained
  captured output would distort the allocation measurement.
- `--log-level=CRITICAL` and `--log-file-level=CRITICAL`: The default is configured
  DEBUG for each. We override it because retained debug records would distort
  the allocation measurement.
- `--log-file=/dev/null`: The default is configured pytest.log. We override it
  because measurement runs must not create persistent diagnostic log files.
- `--timeout=120`: The default is configured 30s. We override it because profiled
  allocation workloads need a longer bounded runtime.

Sources: [pytest-memray 1.11.0 options](https://pytest-memray.readthedocs.io/en/latest/usage.html),
[pytest logging/capture](https://docs.pytest.org/en/stable/reference/reference.html),
and [pytest-timeout 2.4.0](https://pypi.org/project/pytest-timeout/2.4.0/).

## Calibration

Calibrate on Ubuntu 24.04, the same operating system family as CI's `ubuntu-24.04` runner label,
using `.python-version`, `uv.lock`, uv 0.12.19, and Just 1.57.0. Run ten separate processes per case
without coverage, preserving the command's capture and tracing flags. Use a temporary diagnostic
ceiling while measuring, then commit each case's literal
whole-MiB ceiling as `ceil(1.5 * H / 1048576)`, where H is its largest measured peak in bytes. Stop and
investigate if the calculated ceiling exceeds 32 MiB. Remeasure after interpreter, dependency, or
workload changes and record the reason for changing a ceiling.

The calibration command below uses `uv --locked`: The default is inherited `UV_LOCKED`, otherwise
unlocked resolution. We override it because this standalone command must validate the lockfile
([uv 0.12.x](https://docs.astral.sh/uv/reference/environment/#uv_locked)). For `-m memory`: The
default is configured `not memory`. We override it because calibration measures the memory tier.
For `-n 0`: The default is configured `auto`. We override it because allocation measurements must
run without competing worker processes ([xdist 3.8.0](https://pytest-xdist.readthedocs.io/en/stable/distribution.html)).

```bash
for case in identity-with-alias namespace; do
    for run in {1..10}; do
        uv run --locked --group memory -- pytest tests/memory -m memory -n 0 -k "$case" \
            --memray --trace-python-allocators \
            --memray-bin-path="memory-reports/baseline/$case/$run" --capture=no \
            --log-level=CRITICAL --log-file=/dev/null --log-file-level=CRITICAL --timeout=120
    done
done
```

The plugin's `memory-reports/baseline/<case>/<run>/metadata/*.metadata` files record exact
`peak_memory` bytes. The console reports rounded peaks and the largest allocating stacks. Binary
captures use Memray's aggregated format; `memray stats` does not support that format. Use an official
reporter such as `uv run --group memory -- memray flamegraph <trace.bin>` to inspect allocation stacks.
Keep traces, raw output, and comparison harnesses untracked.

Prove sensitivity by temporarily retaining every admitted encoded value in an extra list outside
normal cache accounting. Run both cases and require ceiling failures while structural assertions
still complete. Remove the fault before committing. For profiling overhead, use a temporary local
harness that bypasses only the activation check and leaves the workload intact; do not profile that
comparison.

### Measured baseline

Measurements on 2026-10-04 used an x86-64 Ubuntu 24.04.3 disposable container, CPython 3.14.6,
uv 0.12.19, Just 1.57.0, and the committed lockfile (pytest 9.1.1, pytest-memray 1.11.0,
Memray 1.20.0). Each range contains ten fresh processes. The interpreter, dependencies, and command
flags match the CI configuration. Calibration uses the same Ubuntu 24.04 family as CI's
`ubuntu-24.04` runner label; the point release, host CPU, and runner load can differ.

| Case                | Peak range (bytes)  | Maximum H (bytes) | Ceiling | Profiled body (s) | Process wall time (s) | Trace size (bytes) |
| ------------------- | ------------------- | ----------------- | ------- | ----------------- | --------------------- | ------------------ |
| Identity with alias | 4,430,595–4,430,815 | 4,430,815         | 7 MiB   | 1.743–1.813       | 2.373–2.467           | 28,101–28,233      |
| Namespace           | 4,393,505–4,393,670 | 4,393,670         | 7 MiB   | 1.231–1.299       | 1.879–1.967           | 24,121–24,196      |

Both maxima produce 7 MiB under the calibration rule, and every healthy run is below its ceiling.
The marker spells this as `"7 MB"`; pytest-memray interprets MB in units of 1,048,576 bytes.
The plugin's allocation reports attribute approximately 3.9 MiB of the peak live set to retained BSON
encoding allocations, with another 192 KiB of transient encoding allocations. BSON encoding dominates
the observed allocation stacks; these stacks do not establish a CPU bottleneck.

Ten fresh processes calling the same workload directly, with fixture setup outside timing and no
profiler, measured identity body times of 0.450–0.464 s (median 0.461 s) and namespace body times of
0.340–0.383 s (median 0.349 s). Profiled body medians were 1.765 s and 1.238 s, respectively: 3.83×
and 3.55× overhead. Process wall medians were 2.415 s versus 0.730 s for identity and 1.899 s versus
0.623 s for namespace. The direct-call harness bypasses the activation fixture and pytest's profiler
hooks while preserving workload assertions. Profiler boundary durations came from Memray's official
`FileReader.metadata` timestamps.

Temporarily wrapping the core's encoder to retain every encoded value raised identity peak usage to
571,380,994 bytes and namespace peak usage to 571,347,729 bytes. Both runs completed structural
assertions and exited with a Memray ceiling failure, exposing the allocation stacks in the console.
The injected wrapper was removed; it is not part of the tests.

## CI and failure diagnostics

The `Cache memory regression guard` job in `.github/workflows/test.yml` runs on Ubuntu 24.04 when the
existing Python-validation scope selects a pull request. It waits for Prek and formatting checks and
has a ten-minute timeout. Unrelated documentation changes do not start the workload. CI runs the same
`just test-memory` command and derives no threshold from a cache or previous run.

On failure, the job keeps `memory-reports/` as a seven-day artifact, including binary allocation traces
and exact peak metadata. All payloads are synthetic. The original command failure stays visible in
the job log, including startup failures that produce no trace. Locally, reports appear in the ignored
`memory-reports/` directory.
