# Proposal

## Why

The [benchmark guide](../../../docs/user/benchmarks/index.md) shows an illustrative latency chart, and the [stream-cost reports](../../../docs/user/benchmarks/stream-cost.md) measure reads and writes in separate phases. Neither shows what happens when several application worker processes, each with its own manager, serve reads while writes are invalidating the cached documents. The [shared worker cache study](../../../docs/development/research/shared-worker-cache-feasibility.md) registered such an `active` phase, but its futility rule stopped the study before that phase ran. Without this evidence, users can't compare cached reads with direct reads under mixed load across workers, and the [shared-invalidation investigation #87](https://github.com/alessio-locatelli/client-query-cache/issues/87) has no steady-state baseline to build on.

## What Changes

- Preregister one narrow steady-state workload in which reads and writes run at the same time. It compares direct MongoDB reads with independent per-worker managers at one and four worker processes, using the parameters in [design.md](design.md#workload-registration).
- Reuse the shared worker cache harness by driving it from the registration. The v4 shared-cache registration keeps planning the same cells.
- Report the measures listed in the delta spec. Deliver a development research report, plus concise public figures and their limits in the benchmark and deployment guides.
- Add a documented and continuously verified multi-worker launch to the FastAPI catalogue example.
- Record the decision not to compare against a shared Redis cache ([design.md](design.md#no-shared-redis-comparison)).
- Leave timed fault trials (connection loss, failover, lost resume history, worker restart) to the sibling change `benchmark-worker-fault-recovery`.

## Capabilities

### New Capabilities

- `multi-worker-benchmarking`: Reproducible evidence comparing direct reads with independent per-worker managers across application worker processes while reads and writes run together.

### Modified Capabilities

- `usage-examples`: The catalogue example gains a verified multi-worker server launch.

## Impact

- Code: `benchmarks/stream_cost/shared_cache/` (`protocol.py`, `workload.py`, `window.py`, `run.py`, `analysis.py`) becomes registration-driven, with tests under `tests/benchmark/stream_cost/`.
- Registration: new `reports/concurrent-worker-workload/v1/`.
- Example: `examples/fastapi_catalogue_example.py` adds `uvicorn` to its inline script dependencies. `tests/examples/test_examples.py` covers the new launch. No project dependency changes.
- Docs: a new development research report, plus updates to `docs/user/benchmarks/index.md`, `docs/user/operations/deployment.md`, `docs/user/examples/fastapi.md`, `examples/README.md`, and any `context7.json` rules whose guidance changes.
- The library's public interfaces don't change.
