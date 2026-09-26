# Proposal

## Why

Every existing benchmark and integration tier runs against a disposable, single-node `testcontainers` replica set on the local machine. That setup cannot show whether the cache is worth its cost against a real, network-attached, multi-tenant MongoDB deployment, where round-trip latency, connection pooling, and change-stream propagation behave very differently than against localhost. Nothing in the suite currently proves the cache's core claim — a meaningful speedup over uncached PyMongo — under those realistic conditions, and nothing would catch a regression that only shows up there (e.g., an extra round trip per read, or a network-usage blowup).

## What Changes

- Add a new benchmark test that connects to a real, externally hosted MongoDB replica set (e.g., a free-tier Atlas cluster) using a connection string read from the contributor's gitignored `.env` file.
- The test drives a small, realistic two-process workload against that cluster: one process continuously writes/updates documents, another continuously reads them — once through `CacheManager`, once directly through `pymongo` with no cache — sized to stay well within a free cluster's shared throughput and storage limits and to complete in well under 20 seconds.
- The test asserts the cached path is at least twice as fast as the direct, uncached path in the same run (a relative comparison that self-normalizes against shared-cluster noise).
- The test also asserts wall-clock time (with a generous margin) and server round-trip count (exact, since it's deterministic) stay within hard-coded ceilings derived from an initial recorded run, to catch a regression that would not show up in the relative cache-benefit ratio (e.g., both paths getting slower together, or an extra round trip per read).
- The test is tagged `benchmark` and self-skips (with a visible, explicit reason) whenever it is running on CI or whenever the real-server connection string is not configured, so it runs by default for whoever holds the cluster's credentials without breaking anyone else's `just tests_and_coverage`.
- Document the new `.env` variable and how to obtain/configure a compatible free-tier cluster in `CONTRIBUTING.md`.

## Capabilities

### New Capabilities

- `real-server-benchmarking`: a benchmark test tier that measures the cache's real-world benefit and guards against regressions against a real, externally hosted MongoDB deployment, distinct from the disposable local replica set used by every other tier.

### Modified Capabilities

(none — `test-environment`'s existing tiers, and `continuous-integration`'s requirement that CI not depend on a shared external database, already accommodate a benchmark that self-skips outside a configured local environment; no requirement in either capability changes.)

## Impact

- New test module(s) under `tests/benchmark/` plus a small helper module (connection-string loading, workload driver, hard-coded thresholds) under `benchmarks/` or `tests/benchmark/`, following the existing `benchmarks/stream_cost` + `tests/benchmark/stream_cost` split.
- `justfile`'s `pytest` and `tests_and_coverage` recipes gain a conditional `uv run --env-file .env` when `.env` exists at the repo root, so the connection string reaches the test process without a new runtime dependency (`uv` already refuses a missing `--env-file` path outright, so the recipes must guard the flag on the file's presence).
- `CONTRIBUTING.md` gains a short section on the new `.env` variable and free-tier cluster setup.
- No production code in `src/client_query_cache` changes.
