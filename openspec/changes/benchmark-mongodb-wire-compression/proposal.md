# Proposal

## Why

The library keeps one MongoDB change stream open per active database and manager, but the existing benchmark cannot measure its direct-path bytes with wire compression enabled. There is no controlled evidence comparing MongoDB server CPU, latency, and network use for no compression, Snappy, zlib, and Zstandard, so the library cannot give an evidence-backed compression recommendation.

## What Changes

- Add a reproducible local benchmark that compares all four wire modes on matched cache and no-stream workloads, including idle polling and active writes.
- Record MongoDB container CPU, latency distributions, direct-path bytes in both directions, negotiated compressor, and workload context in versioned reports. Retain repeated measurements so run-order and host noise are visible.
- Permit the dedicated byte proxy to measure compressed direct-path traffic while preserving its topology and scope limits.
- Document the measured default recommendation for a caller-owned PyMongo client, with the change stream's cost and the recommendation's workload limits made explicit.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `stream-cost-benchmarking`: accept compressed traffic on the isolated direct path and require a matched four-mode comparison and evidence-based recommendation.

## Impact

The benchmark runner, dedicated client and byte proxy, report validation, retained benchmark reports, and `docs/stream-cost-benchmarks.md` are affected. The README may link to the new guidance. Snappy needs a benchmark-only dependency; this project's Python 3.14 and PyMongo use the standard library for Zstandard and zlib. The public cache API and its use of the caller's PyMongo client do not change.
