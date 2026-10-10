# Proposal

## Why

The [shared worker cache study](../../../docs/development/research/shared-worker-cache-feasibility.md) halved group memory, but it stopped at screening. Request P99 and total CPU per request exceeded the registered limits because every hit paid a Python owner round trip. [Issue #229](https://github.com/alessio-locatelli/client-query-cache/issues/229) asks for a design that removes or shrinks that per-read cost, judged by a new preregistered study with the same gate.

## What Changes

- Measure exploratory per-hit cost floors for the candidate families in [design.md](design.md#candidate-families) before building a full prototype. Build at most two full candidates, chosen by the preregistered [selection rule](design.md#floor-diagnostics-and-selection).
- The leading candidate is a shared index. The owner publishes its resident identity entries and validity words into read-only shared memory, and workers serve hits locally without a round trip. Misses, finds and admissions keep the existing owner RPC.
- Implement the shared index and any native owner hot path as a Rust extension built with PyO3 and maturin. The extension lives in the repository as a separate distribution outside the published package, and its shipping form is left to a later integration change.
- Add a small residency and invalidation listener seam to `CacheCore`, which lets the owner keep the published index in step with the core. Standalone behaviour and public interfaces are unchanged.
- Preregister registration version 5 under `reports/shared-worker-cache/v5/` with the version 4 workload and gate, the candidate paths and the amended integration criterion in [design.md](design.md#registration-version-5). Then run the registered phases and record the verdict.
- Make the Rust toolchain part of contributor setup and CI while the extension is in the tree.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `shared-cache-benchmarking`: Adds floor-gated candidate selection, safety requirements for locally validated hits, worker write isolation, non-competing owner-liveness detection, bounded shared-memory reclamation and reproducible native builds.
- `development-environment`: The contributor container and setup build the in-repository native extension from locked sources.

## Impact

- Code:
  - a new Rust crate and maturin distribution at `native/shared-index/`, added as a uv workspace member in the `dev` group;
  - shared-index owner and adapter paths in `benchmarks/stream_cost/shared_cache/`;
  - a listener seam in `src/client_query_cache/_core/lru.py` and `manager.py`;
  - floor diagnostics under `research/shared_index_floors/`;
  - tests under `tests/shared_cache/` and `tests/core/`.
- Tooling: `Containerfile`, CI jobs that sync the `dev` group, `.github/dependabot.yml` (Cargo) and `docs/development/executable-version-updates.md`.
- Registration and reports: `reports/shared-worker-cache/v5/` and an updated `docs/development/research/shared-worker-cache-feasibility.md`.
- Sequencing: registration depends on the registration-driven harness from `benchmark-concurrent-worker-workload` (its tasks 1.1–1.2).
- The published package, its runtime dependencies and its public API do not change.
