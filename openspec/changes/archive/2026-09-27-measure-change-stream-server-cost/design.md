# Design

## Context

See proposal.md - Why and What Changes. This design also records findings from directly testing the Atlas Admin API against this project's actual real-deployment cluster (project `backend`, cluster `Cluster0`, confirmed `instanceSize: M0`), so a future session does not need to re-derive them empirically:

- `atlas metrics processes` returns real, non-zero data on this M0 cluster for `NETWORK_BYTES_IN`, `NETWORK_BYTES_OUT`, `NETWORK_NUM_REQUESTS`, and `OPCOUNTER_QUERY`. A live test run was directly correlated against the metric timeline: four flat-zero one-minute buckets, then a bucket showing `NETWORK_BYTES_IN=1648.5`, `NETWORK_BYTES_OUT=2275.0`, `OPCOUNTER_QUERY=2.18` at exactly the bucket the test ran in.
- `PROCESS_CPU_USER`, `PROCESS_CPU_KERNEL`, and `PROCESS_NORMALIZED_CPU_USER` return HTTP 200 with an empty `dataPoints` array on this M0 cluster — not an error. This is a real tier limitation, not a transient gap: process-level CPU is not available on this deployment.
- `SYSTEM_CPU_USER` is not a valid measurement name in the current Admin API version at all (`HTTP 404 INVALID_METRIC_NAME`) — do not substitute it for process CPU.
- The project's M0 cluster otherwise shows occasional non-zero background blips even with nothing intentionally running against it (Atlas's own housekeeping, or a contributor's own prior manual runs) — a single sample cannot be cleanly attributed to the benchmark alone.
- Running `tests/benchmark/real_server/test_cache_benefit.py` repeatedly back-to-back showed a real cold-start cost: 22.41s (failed against the 20s ceiling) on the first connection in a session, dropping to 19.56s then 16.71s on immediate reruns. This is consistent with per-connection DNS/TLS/Atlas-proxy-routing warm-up, not random cluster jitter.
- `RealMongoDbUri` (`tests/benchmark/real_server/env.py`) is `NewType("RealMongoDbUri", str)`, which is erased at runtime - the fixture value is a plain `str`. Pytest's default assertion-rewriting explanation prints `repr()`/`str()` of any value that appears directly in a failing `assert` expression, and `--showlocals`/`-l` (not on by default, but a common ad hoc debugging flag) prints every local variable's `repr()` for the failing frame regardless of whether it appears in the assertion. Verified empirically during implementation: a plain failing assertion that never mentions the fixture does **not** print it under this project's actual (non-`--showlocals`) pytest invocation - the exposure is real but conditional on `--showlocals` or on the fixture appearing directly in a failing assertion, not "happening right now" unconditionally as originally recorded here.
- **Correction discovered during implementation:** `benchmarks/stream_cost/measurement.py`'s `measure_controlled()` brackets one combined operation per controlled run (see `run.py::_run_variant` calling `_sample_variant`), which runs the raw and cache reads _interleaved_ in the same timed window (`workload.py::run_paired_reads`) alongside the shared writes. Each retained report therefore has exactly one `container_cpu_seconds` and one `direct_path_bytes` pair for the whole run - not one per raw/cache variant. There was nothing to "pair" for an explicit change-stream-cost comparison; see the revised Decision below for how this change now produces genuinely separate raw-path and cache-path measurements.

## Goals / Non-Goals

**Goals:**

- Local CPU and network cost of watching the change stream, under concurrent insert+read: answered by measuring the `BALANCED` workload's raw path and cache path as two independent controlled runs and presenting their `container_cpu_seconds`/`direct_path_bytes` side by side as an explicit comparison (see the revised Decision below - this required new, narrowly-scoped measurement code once implementation showed the existing single combined measurement could not be split after the fact).
- Real-deployment network cost of watching the change stream: answered by adding Atlas bandwidth evidence around the existing cached/uncached phases, non-gating.
- Keep the real-server benchmark's credential handling and timing honest before extending it further.

**Non-Goals:**

- Real-deployment CPU cost: confirmed unavailable on this project's M0 tier (see Context). Not pursued in this change, and not blocked on a tier upgrade per the project's stated constraint (M0 or nothing).
- Making Atlas bandwidth evidence, or the local network-byte proxy comparison, a pass/fail gate. Both are evidence only - see Decisions.
- Changing `real-server-benchmarking`'s 20-second wall-clock ceiling. The pre-flight ping is added first; whether the ceiling needs to move is answered empirically after that, not decided here (see Open Questions).
- Enabling `--direct-path-proxy` by default for every `stream-cost-benchmarking` run. It adds proxy overhead and explicitly refuses TLS/compression/discovery/shared-connection configurations, so it stays opt-in; this change only requires that one retained report run uses it so the network-cost comparison has data to show.

## Decisions

**Atlas invocation: subprocess call to the `atlas` CLI, not a Python SDK or direct Admin API HTTP client.**
The contributor already has `atlas` installed and authenticated for this project. Shelling out to it reuses that session (no API key to provision or store) and adds no new Python dependency. A direct HTTP client against the Admin API would need its own API-key credential - a second credential type this project's single-`.env`-variable model doesn't otherwise have. This mirrors the existing `real-server-benchmarking` philosophy of minimal added surface (see the archived `add-real-server-benchmark` design's non-goals).

**Bandwidth metric set: `NETWORK_BYTES_IN`, `NETWORK_BYTES_OUT`, `NETWORK_NUM_REQUESTS`, `OPCOUNTER_QUERY`. No CPU metrics requested.**
These four are the ones confirmed to return real data on this project's M0 cluster (see Context). Requesting `PROCESS_CPU_USER`/`PROCESS_CPU_KERNEL` would silently return nothing every time - not worth the API call or the code path to handle "empty but not an error." `CONNECTIONS` was also tested and returned all-zero across the test window despite real connections occurring; it is not included as a reliable signal.

**Granularity: `PT1M`, no attempt at `PT10S`.**
`PT10S` premium monitoring requires M40+; this project's M0 tier does not qualify. A single 1-minute bucket can include activity beyond the exact phase window - an accepted, disclosed limitation of using this tier at all, not something this change tries to engineer around.

**Bandwidth evidence is non-gating, matching this repo's existing precedent for noisy cross-run measurements.**
`stream-cost-benchmarking`'s own container-CPU numbers are already documented as evidence, explicitly not a pass/fail gate, because of cross-run/cross-host noise on a _local, single-tenant_ container. The M0 cluster is multi-tenant, coarser-grained, and was observed to show non-zero background activity even at rest - strictly noisier than the case that precedent already exists for. A numeric threshold here would either be loose enough to never catch a real regression or tight enough to fail on Atlas's own background activity.

**Missing Atlas data (API error, `atlas` CLI absent or unauthenticated, empty CPU-style response) is handled the same way: log and omit that evidence, never fail the benchmark.**
Since this evidence never gates the result, there is no reason to treat its absence differently from an ordinary transient failure.

**Credential fix: replace the bare `NewType` with a small wrapper whose `__repr__`/`str()` return a redacted value; production connection calls use an explicit accessor for the real string.**
This directly closes the pytest-traceback leak path (see Context) at its source, rather than trying to suppress it via pytest configuration (`--tb=short`/`-p no:...`), which would also hide legitimately useful failure context for every other local variable in that test.

**Local network/CPU comparison: two additional, narrowly-scoped controlled measurements for the `BALANCED` workload, not a reporting-only change.**
Implementation showed the existing single combined measurement interleaves raw and cache reads in one timed window, so there is no existing per-variant `container_cpu_seconds`/`direct_path_bytes` to pair (see the corrected Context note above). `run.py` now runs two extra `measure_controlled()`-bracketed operations for `BALANCED` variants only, each against its own disposable collection so it does not disturb the existing combined report: a raw-only pass (`workload.py::perform_raw_only_reads` plus the shared writes, no `CacheManager`) and a cache-only pass (`workload.py::perform_cache_only_reads` plus the same shared writes, through a fresh `CacheManager` so its change stream is active). `report.py::build_report` accepts this pair as an optional `change_stream_cost` argument and, only when provided, adds a `measurement.change_stream_cost_comparison` section (schema v1, additive and optional - every other retained report is unchanged). This keeps the blast radius scoped to the `BALANCED` workload and does not touch `idle`/`read_heavy`/`write_dominant` reports' existing shape. The retained report set was regenerated once with `--direct-path-proxy` enabled so all workloads (including the three `BALANCED` sizes) carry real `direct_path_bytes`, satisfying the requirement that at least one retained `BALANCED` run has this evidence without changing the manual GitHub Actions workflow's default (still proxy-off).

## Risks / Trade-offs

- **Atlas CLI is a new local prerequisite.** → Only for the same single contributor who already needs `REAL_MONGODB_URI` configured to run this benchmark at all; it does not add a barrier for anyone else, and its absence degrades to "missing evidence," not a failure.
- **A contributor's own Atlas project ID/name is inherently specific to their account.** → Sourced from a new local `.env` variable (mirroring `REAL_MONGODB_URI`'s existing pattern), never hard-coded or committed.
- **Background noise on the cluster means a single evidence sample cannot be cleanly attributed to the benchmark alone.** → Accepted; this is exactly why the evidence is non-gating rather than an assertion.
- **The pre-flight ping does not guarantee eliminating cold-start variance in every case** (e.g., a longer idle gap could still show warm-up cost on the _timed_ window if the ping's own connection doesn't share the pool). → Accepted, disclosed limitation; implementation should reuse the same client/connection the timed phases use so the ping's warm-up actually transfers.

## Migration Plan

Purely additive. Nothing existing changes behavior for a contributor without `REAL_MONGODB_URI` configured (the benchmark still skips entirely) or without `atlas` CLI authenticated (bandwidth evidence is simply absent). Rollback is reverting the new report/collection code and the `env.py` credential-wrapper change; no data or schema migration is involved.

## Open Questions

- Whether `real-server-benchmarking`'s 20-second total-duration ceiling needs to move now that a pre-flight ping absorbs cold-start cost outside the timed window. This is answered empirically during implementation (re-run the benchmark warm, with the ping in place, and compare against the existing ceiling) and does not change this change's specs, approach, or task breakdown either way.
  - **Resolved during implementation:** with the pre-flight ping in place, eight consecutive runs against the project's M0 deployment measured `overall_duration` at 17.26s, 16.52s, 16.05s, 16.22s, 16.82s, 19.60s, 17.55s, and 17.56s — all comfortably under the existing 20-second ceiling, including the run following the longest gap between invocations. The ceiling does not need to move.
