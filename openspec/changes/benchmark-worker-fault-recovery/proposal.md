# Proposal

## Why

Current stress tests cover stream recovery within a manager, but do not verify
that separate direct and cached worker processes continue to read correct data
through MongoDB failover, TCP loss, stream-history loss or process replacement.
This change provides real container-backed regression coverage for those
behaviors.

The quantitative study remains unfinished. Its V8 observer-overhead result and
stop rule are recorded in
[`reports/worker-fault-recovery/research-outcome.md`](../../../reports/worker-fault-recovery/research-outcome.md).

## What Changes

- Add a disposable three-member replica-set topology and a small test-only
  process-control harness.
- Add multi-process integration coverage for primary stepdown, TCP connection
  loss, stream-history loss and worker kill/replacement, preserving the direct
  and independent-cache distinctions where applicable.
- Keep the quantitative recovery study pending in this OpenSpec change; this PR
  makes no recovery-time or performance claims.

The change depends on the archived
`2026-10-11-benchmark-concurrent-worker-workload` capability.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `multi-worker-benchmarking`: Defines real multi-process fault-recovery
  regression coverage.

## Impact

- Code and tests: `benchmarks/stream_cost/topology.py` and
  `tests/benchmark/stream_cost/`.
- Research history: the concise V1–V8 outcome is retained at
  `reports/worker-fault-recovery/research-outcome.md`.
- The library's public interfaces and user-facing performance guidance do not
  change.
