# Proposal

## Why

Neither existing benchmark tier lets anyone answer "does watching the change stream cost extra server CPU or network bandwidth, concurrently with inserts and reads?" `real-server-benchmarking` proves the cache is faster and catches an extra round trip, but never looks at server-side resource cost. `stream-cost-benchmarking` already collects MongoDB-container CPU and (opt-in) direct-path bytes per workload variant, but never surfaces those raw (no stream) vs. cache (stream-watching) numbers as an explicit change-stream-cost comparison, so the evidence exists without anyone being able to read it that way. Closing this gap requires reusing what each tier already collects rather than adding a new benchmark tier.

## What Changes

- `real-server-benchmarking`: collect non-gating Atlas Admin API network-bandwidth evidence (`NETWORK_BYTES_IN`, `NETWORK_BYTES_OUT`, `NETWORK_NUM_REQUESTS`, `OPCOUNTER_QUERY`) around the existing cached (stream-watching) and uncached (no stream) phases, via the already-installed, already-authenticated `atlas` CLI. Scoped to what the project's M0 deployment actually returns: process-level CPU metrics (`PROCESS_CPU_USER`/`PROCESS_CPU_KERNEL`/normalized variants) are confirmed unavailable on M0 (the API returns an empty measurement list, not an error) and are explicitly out of scope for this benchmark.
- `real-server-benchmarking`: fix the credential-leak mechanism that currently prints the real connection string (via pytest's default traceback locals) on any assertion failure in this test.
- `real-server-benchmarking`: add a pre-flight connectivity ping before the timed benchmark window, to separate genuine per-connection cold-start latency (confirmed present: ~22s cold vs. ~17-19.5s warm on repeated runs) from the workload itself, before deciding whether the existing 20-second ceiling needs to change.
- `stream-cost-benchmarking`: make the `BALANCED` workload's (concurrent insert+read) raw-vs-cache comparison of `container_cpu_seconds` and, in `--direct-path-proxy` mode, `direct_path_bytes_sent`/`direct_path_bytes_received` an explicit, retained "change-stream resource cost" report section, both already collected per controlled run but never presented as this specific with/without-the-stream comparison.

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `real-server-benchmarking`: adds non-gating server-side network-bandwidth evidence collection (Atlas-only, M0-scoped), a credential-redaction requirement, and a pre-flight connectivity check ahead of the timed window.
- `stream-cost-benchmarking`: adds a requirement that reports surface the `BALANCED` workload's raw-vs-cache CPU and network-byte numbers as an explicit change-stream resource-cost comparison.

## Impact

- `tests/benchmark/real_server/env.py`: `RealMongoDbUri` gains redacted `repr`/`str` so it can no longer leak via pytest traceback locals.
- `tests/benchmark/real_server/workers.py`, `test_cache_benefit.py`: pre-flight ping before the timed window; Atlas CLI invocation (subprocess, reusing the contributor's existing authenticated session) to collect network-bandwidth measurements bracketing each phase.
- `benchmarks/stream_cost/report.py`, `docs/stream-cost-benchmarks.md`: explicit change-stream-cost comparison section derived from already-collected `BALANCED`-workload measurements.
- `CONTRIBUTING.md`, `README.md`: document the new evidence and how to reproduce it.
- No production code in `src/client_query_cache` changes.
- No new Python dependency: the `atlas` CLI is invoked as a subprocess, not imported as a package.
