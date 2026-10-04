# Design

## Context

See [proposal.md](proposal.md) for motivation. `CacheCore.admit_identity()` and `admit_namespace()` encode values to BSON and charge `len(encoded)` against `WeightedLru`. The budget excludes Python key objects, identity records, alias maps, and the namespace reclamation index. Existing `tests/core/test_lru_storage.py` checks accounting and eviction with short sequences; `test_manager_state_machine.py` checks ordering over a small identity space.

Both manager execution models share this core. `record_write()` advances generations; stale values can remain resident until lookup, replacement, eviction, or namespace reclamation. The workload must not assert that every ordinary write immediately frees its entry. `clear_namespace()` physically reclaims namespace entries, whereas `close()` clears the LRU and namespace registries.

`.github/workflows/test.yml` already selects Python validation via `scripts/ci_scope.py` and stages expensive jobs behind `prek` and `prettier`. `pytest.ini` declares execution tiers, `tox.ini` selects them, and `just tests_and_coverage` provides a separate coverage invocation. These mechanisms should be extended rather than adding a custom benchmark runner.

## Goals / Non-Goals

**Goals:** Detect cumulative retention outside BSON accounting with a deterministic, bounded-duration workload and actionable allocation traces. Establish that the guard catches a known retention fault while passing repeated healthy runs.

**Non-Goals:** No process-RSS promise, byte-for-byte equality between heap usage and BSON budget, telemetry soak test, dynamic namespace churn, MongoDB profiling, or proof of cursor/thread/asyncio-task cleanup. Core closure is a reclamation checkpoint, not a manager lifecycle test.

## Decisions

### 1. Prioritize cache churn with fixed cardinality

The highest-value first target is cache payload and metadata retention under eviction and namespace reclamation. This follows the existing bounded-cache contract, avoids database timing, and creates a large signal relative to a small healthy live set. A telemetry-only test would protect a narrower bounded deque; a mixed RSS soak would confound allocator retention, driver pools, and workload effects. Full manager cleanup needs a distinct workload with asynchronous ownership assertions.

Use one parametrized test in `tests/memory/test_cache_churn.py`, with identity-with-alias and namespace-guarded cases. Each case uses two fixed namespaces sharing a 4 MiB budget and a 128 KiB maximum entry size. Prepare a deterministic 64 KiB synthetic payload from a seeded Faker fixture before the test body. Keep identity/query keys short and unique across cycles; do not retain a document corpus, decoded results, snapshots, or admission captures.

Run eight cycles of 1,024 fresh admissions, alternating namespaces. For identity entries, use `begin_identity_admission()` and `admit_identity(..., alias=...)`; for namespace entries, use `capture_namespace_generation()` and `admit_namespace()`. Confirm each outcome is `ADMITTED` and an immediate lookup hits. Every sixteenth admission, call `record_write()` for the just-admitted identity, confirm the corresponding lookup misses, and recapture/readmit the value before confirming a hit. Each helper invocation releases its transient input/result references on return.

After each block of 128 fresh admissions, assert `used_bytes <= shared_budget_bytes`, accumulated evictions are positive, and the sum of namespace entry-index sizes equals resident entry count. At these quiescent checkpoints, identity records and aliases must be backed by resident identity entries; no captures remain in flight. After each cycle, clear both namespaces and assert zero entry count, zero BSON usage, and empty entry indexes, identities, and aliases. Keep the core alive through all cycles so accumulating state cannot be hidden by recreation. Close it and assert zero usage at the end; fixture teardown guarantees closure if an assertion fails.

This processes at least 512 MiB of payload per case while allowing only 4 MiB of encoded values to stay resident. Exact runtime and healthy allocation peaks are unmeasured at proposal time.

### 2. Use pytest-memray's peak ceiling with Python allocation tracking

Add a platform-qualified `memory` dependency group containing pytest-memray for Linux and macOS; verify a stable release supports the repository's CPython/Pytest versions during dependency resolution. CI gates on Linux only. Ordinary commands do not enable the plugin. No new runtime dependency is added to the package.

The [pytest-memray usage reference](https://pytest-memray.readthedocs.io/en/latest/usage.html) defines `limit_memory` as peak/high-watermark tracked allocations. Use `@pytest.mark.limit_memory(...)` on each case and `--trace-python-allocators` to see allocations behind Python arenas. This is neither RSS nor cumulative allocation volume. Retained allocations remain in the live set and eventually raise the peak, even if cache byte accounting stays correct. Structural assertions catch smaller metadata defects beneath the byte ceiling.

Use all-thread tracking, the plugin default; the workload itself starts no background workers. Do not use `--fail-on-increase`, historical pytest-cache baselines, `limit_leaks`' per-stack budgets, native-stack reporting, or custom allocation readers. A retained-bytes delta profiler would provide more precision but adds analysis machinery unnecessary for this first guard.

Calibrate each case in ten separate processes on the same Ubuntu/interpreter/locked dependency configuration as CI, without coverage. Let H be the largest healthy peak in bytes. Commit a literal ceiling of `ceil(1.5 * H / 1048576) MiB`, independently per case, with a maximum permitted ceiling of 32 MiB. The rule reserves 50% measured headroom and limits the ceiling to one sixteenth of processed payload. No measured ceiling is claimed in this proposal. If calibration exceeds that bound, investigate harness retention and allocator compatibility before proceeding; do not change the rule silently. Remeasure after interpreter, dependency, or workload changes and document the reason for threshold changes.

Prove sensitivity in a temporary reversible fault experiment: retain each encoded value in an extra list outside normal budget/reclamation accounting, leaving structural invariants intact. Run each case and require a Memray ceiling failure. Remove the fault before completion; do not commit the injected fault or a test of the test harness. Record the experiment in the concise calibration summary.

### 3. Isolate the command and reduce harness retention

Register `memory` and `limit_memory` markers and set the default marker selection to `not memory`. Memory tests carry only the `memory` execution-tier marker. Audit explicit `-m` selections in Just/tox so every provided ordinary command excludes this tier; the dedicated command overrides selection with `-m memory` and a concrete test directory. Add a fixture that fails if the memray option is absent or false, so manually selecting these tests cannot silently bypass profiling. Pytest's no-tests exit status remains a failure.

Provide `just test-memory` and a matching opt-in tox environment (outside `envlist`), using the locked dependency groups required by the harness. The Just recipe directly invokes uv/pytest, avoiding the container bridge used by `just pytest`. Its pytest arguments are:

```text
tests/memory -m memory --memray --trace-python-allocators
--memray-bin-path=memory-reports --capture=no -p no:logging --timeout=120
```

Disabling pytest log/stdio capture prevents per-admission debug logs from becoming a retained workload. The plugin writes traces under ignored `memory-reports/`; errors remain visible on the console. The profiling boundary is the test body; fixtures/imports lie outside it. Baselines and CI must use this same boundary and flags. On unsupported platforms, the dedicated command fails visibly with a short supported-platform hint and an official Memray documentation link; normal validation still works.

### 4. Extend existing CI scope and diagnostics

Add a dedicated Ubuntu 24.04 job in `test.yml`, with `needs: [scope, prek, prettier]`, the existing Python scope condition, read-only permissions, and a ten-minute timeout. Reuse checkout and setup-toolchain pins, synchronize `uv.lock`, and run `just test-memory`. Existing Python scope already includes the workflow, dependencies, interpreter, Just recipes, pytest configuration, Python source, and shared toolchain setup; no new scope selector is needed.

On failure upload `memory-reports/` with seven-day retention using the existing upload-artifact pin. Missing traces do not hide the command error. No raw diagnostic output belongs in Git. Put a short command/link in `CONTRIBUTING.md` and the detailed workload, scope, calibration commands, per-case peaks/ceilings, runtime, and sensitivity result in `docs/development/memory-regression-tests.md`. No README expansion is needed.

### 5. Resource costs and measurement evidence

| Operation                       | Relevant cost                                                                                        |
| ------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Encode admission and decode hit | O(payload bytes), transient BSON/document allocations; no network calls                              |
| Insert and evict                | LRU work and reclamation proportional to displaced entries; resident payload bounded by budget       |
| Metadata checkpoint             | O(resident entries), temporary observations bounded by the live set                                  |
| Clear namespace                 | O(resident entries), transient reclamation list bounded by live entries                              |
| Profile                         | Python allocator tracing adds CPU overhead and trace-file disk I/O proportional to allocation events |

Keep synthetic data generation outside tracking and every result short-lived. BSON encode/decode and allocation tracing are expected to dominate; this is an inference, not a measurement. During implementation record largest peaks, chosen ceilings, ten-run peak ranges, wall-clock durations with and without profiling, and the observed dominant allocation stacks. Store only concise Markdown findings and reproduction commands. Include the profiling measurements in the implementation commit body as required by project policy.

## Risks / Trade-offs

- Allocator/toolchain variability → calibrate on CI's exact toolchain, track Python allocations, and retain measured headroom with an explicit ceiling bound.
- Harness logging or retained input data overwhelms the cache signal → disable capture, create no growing history, and inspect healthy allocation stacks before fixing thresholds.
- A small leak stays beneath the ceiling → structural metadata assertions complement the peak gate; this finite workload does not promise detection of every leak.
- Plugin compatibility is not established locally → verify locked resolution and a real profiled invocation before implementation completion; report incompatibility rather than silently skipping.
- Profiling overhead or trace size is excessive → keep two cases and fixed iteration counts; record runtime and trace size during calibration and investigate if the job approaches its timeout.

## Migration Plan

Implementation introduces only opt-in developer commands and a required PR check for the existing Python scope. Activate CI after calibration and the retention-fault experiment succeed. Reverting the memory job, test tier, development dependency, and associated command restores previous validation without any runtime or persisted-data migration.
